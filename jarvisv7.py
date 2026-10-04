import json
import os
import re
import subprocess
import threading
import time
import warnings
import webbrowser
from datetime import datetime, timedelta
import psutil
import requests
from dotenv import load_dotenv
from ollama import chat
from shazamio import Shazam
from testvoix.voice import speak
from importmeteo import get_weather_forecast, reset_weather_cache
from testmanim import create_manim_animation
import asyncio

load_dotenv()
warnings.filterwarnings("ignore")
reset_weather_cache()

# ============================================================
# CONFIGURATION
# ============================================================

MODEL_NAME = "##"  # doit supporter les tools
BLUETOOTH_MAC = "##"
VILLE_PAR_DEFAUT = "##" # Votre ville pour la météo par defaut
MAX_ETAPES_OUTILS = 6  # securite anti-boucle infinie du tool calling

# Applications lancables rapidement (sans passer par le LLM)
APPLICATIONS = {
    "navigateur": ["x-www-browser"],
    "terminal": ["gnome-terminal"],
    "invite de commande": ["gnome-terminal"],
    "calculatrice": ["gnome-calculator"],
    "documents": ["xdg-open", os.path.expanduser("~/Documents")],
    "fichiers": ["nautilus"],
    "editeur de texte": ["gedit"],
    "spotify": ["spotify"],
}

# Registre partage des minuteurs et rappels actifs (permet l'annulation)
TIMERS: dict[str, threading.Timer] = {}


def _notifier(message: str) -> None:
    """Fonction interne appelee par les threads de minuteur/rappel a l'echeance."""
    print(f"\n[RAPPEL ECOULE] {message}")
    try:
        speak(f"Attention ! {message}")
    except Exception as e:
        print(f"Erreur de lecture audio dans le thread : {e}")


# ============================================================
# OUTILS - INFORMATIONS SYSTEME
# ============================================================

def get_system_status(**kwargs) -> str:
    """Recupere l'etat du systeme : processeur, batterie et temperatures."""
    cpu_usage = psutil.cpu_percent(interval=0.1)
    battery = psutil.sensors_battery()
    bat_str = f"{battery.percent}%" if battery else "Non detectee"

    temps = psutil.sensors_temperatures()
    temp_info = []
    if "coretemp" in temps and temps["coretemp"]:
        for entry in temps["coretemp"]:
            label = entry.label if entry.label else "Global"
            temp_info.append(f"{label}: {entry.current}°C")
        temp_str = " | ".join(temp_info)
    else:
        temp_str = "Capteurs indisponibles"

    return f"Charge CPU : {cpu_usage}% | Batterie : {bat_str} | Temperatures : {temp_str}"


def get_heure(**kwargs) -> str:
    """Donne l'heure actuelle."""
    return time.strftime("%H heures %M")


def get_date_du_jour(**kwargs) -> str:
    """Donne la date du jour actuel (jour de la semaine, jour, mois, annee)."""
    jours_fr = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    mois_fr = [
        "janvier", "fevrier", "mars", "avril", "mai", "juin",
        "juillet", "aout", "septembre", "octobre", "novembre", "decembre",
    ]
    now = datetime.now()
    return f"{jours_fr[now.weekday()]} {now.day} {mois_fr[now.month - 1]} {now.year}"


def obtenir_adresse_ip(**kwargs) -> str:
    """Recupere l'adresse IP locale et l'adresse IP publique de la machine."""
    try:
        ip_locale = subprocess.run(
            ["hostname", "-I"], capture_output=True, text=True, check=True
        ).stdout.strip()
        try:
            ip_publique = requests.get("https://api.ipify.org", timeout=3).text
        except Exception:
            ip_publique = "indisponible"
        return f"IP locale : {ip_locale} | IP publique : {ip_publique}"
    except Exception as e:
        return f"Erreur lors de la recuperation de l'IP : {e}"


def lister_processus_gourmands(**kwargs) -> str:
    """Liste les 5 processus consommant le plus de ressources CPU."""
    try:
        processus = sorted(
            psutil.process_iter(["name", "cpu_percent"]),
            key=lambda p: p.info["cpu_percent"] or 0,
            reverse=True,
        )[:5]
        lignes = [f"{p.info['name']} : {p.info['cpu_percent']}%" for p in processus]
        return "Top processus CPU : " + " | ".join(lignes)
    except Exception as e:
        return f"Erreur lors de la recuperation des processus : {e}"


# ============================================================
# OUTILS - CONTROLE SYSTEME
# ============================================================

def bluetooth_on(**kwargs) -> str:
    """Active ou allume le Bluetooth de l'ordinateur."""
    try:
        subprocess.run(["rfkill", "unblock", "bluetooth"], check=False)
        subprocess.run(["bluetoothctl", "select", BLUETOOTH_MAC], check=False)
        subprocess.run(["bluetoothctl", "power", "on"], check=True)
        return "Le Bluetooth a ete active avec succes."
    except Exception as e:
        return f"Erreur lors de l'activation du Bluetooth : {e}"


def bluetooth_off(**kwargs) -> str:
    """Desactive, eteint ou coupe le Bluetooth de l'ordinateur."""
    try:
        subprocess.run(["bluetoothctl", "power", "off"], check=True)
        return "Le Bluetooth a ete desactive avec succes."
    except Exception as e:
        return f"Erreur lors de la desactivation du Bluetooth : {e}"


def wifi_on(**kwargs) -> str:
    """Active le Wi-Fi de l'ordinateur."""
    try:
        subprocess.run(["nmcli", "radio", "wifi", "on"], check=True)
        return "Le Wi-Fi a ete active."
    except Exception as e:
        return f"Erreur lors de l'activation du Wi-Fi : {e}"


def wifi_off(**kwargs) -> str:
    """Desactive le Wi-Fi de l'ordinateur."""
    try:
        subprocess.run(["nmcli", "radio", "wifi", "off"], check=True)
        return "Le Wi-Fi a ete desactive."
    except Exception as e:
        return f"Erreur lors de la desactivation du Wi-Fi : {e}"


def regler_volume(niveau: int, **kwargs) -> str:
    """Regle le volume sonore du systeme sur un pourcentage donne.

    Args:
        niveau: Volume cible en pourcentage, de 0 a 100.
    """
    try:
        niveau_borne = max(0, min(100, int(niveau)))
        subprocess.run(
            ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{niveau_borne}%"],
            check=True,
        )
        return f"Volume regle sur {niveau_borne}%."
    except Exception as e:
        return f"Erreur lors du reglage du volume : {e}"


def couper_son(**kwargs) -> str:
    """Coupe le son du systeme (mute)."""
    try:
        subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"], check=True)
        return "Le son a ete coupe."
    except Exception as e:
        return f"Erreur lors de la coupure du son : {e}"


def activer_son(**kwargs) -> str:
    """Reactive le son du systeme (unmute)."""
    try:
        subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"], check=True)
        return "Le son a ete reactive."
    except Exception as e:
        return f"Erreur lors de la reactivation du son : {e}"


def regler_luminosite(niveau: int, **kwargs) -> str:
    """Regle la luminosite de l'ecran sur un pourcentage donne.

    Args:
        niveau: Luminosite cible en pourcentage, de 1 a 100.
    """
    try:
        niveau_borne = max(1, min(100, int(niveau)))
        subprocess.run(["brightnessctl", "set", f"{niveau_borne}%"], check=True)
        return f"Luminosite reglee sur {niveau_borne}%."
    except Exception as e:
        return f"Erreur lors du reglage de la luminosite : {e}"


def verrouiller_ecran(**kwargs) -> str:
    """Verrouille l'ecran de l'ordinateur."""
    try:
        subprocess.run(["loginctl", "lock-session"], check=True)
        return "L'ecran a ete verrouille."
    except Exception as e:
        return f"Erreur lors du verrouillage de l'ecran : {e}"


def mettre_en_veille(**kwargs) -> str:
    """Met l'ordinateur en veille (suspend)."""
    try:
        subprocess.run(["systemctl", "suspend"], check=True)
        return "Mise en veille en cours."
    except Exception as e:
        return f"Erreur lors de la mise en veille : {e}"


def fermer_application(nom: str, **kwargs) -> str:
    """Ferme une application en cours d'execution d'apres son nom de processus.

    Args:
        nom: Nom du processus ou de l'application a fermer.
    """
    try:
        subprocess.run(["pkill", "-i", nom], check=True)
        return f"Application '{nom}' fermee."
    except subprocess.CalledProcessError:
        return f"Aucune application nommee '{nom}' n'a ete trouvee."
    except Exception as e:
        return f"Erreur lors de la fermeture de l'application : {e}"


# ============================================================
# OUTILS - PRODUCTIVITE
# ============================================================

def creer_minuteur(duree_minutes: float, motif: str = "le minuteur", **kwargs) -> str:
    """Cree un minuteur qui declenche une alerte vocale a l'echeance.

    Args:
        duree_minutes: Duree du minuteur en minutes (peut etre decimale).
        motif: Description courte de ce pour quoi le minuteur est cree.
    """
    def _fin_minuteur():
        TIMERS.pop(motif, None)
        _notifier(f"votre minuteur pour {motif} est ecoule.")

    t = threading.Timer(float(duree_minutes) * 60, _fin_minuteur)
    t.daemon = True
    TIMERS[motif] = t
    t.start()
    return f"Minuteur de {duree_minutes} minute(s) demarre pour '{motif}'."


def programmer_rappel(heure: str, message: str, **kwargs) -> str:
    """A utiliser uniquement pour les rappels a heure fixe : 'a 15h30', 'a 8 heures', 'a 20:00'.

    Args:
        heure: Heure cible au format HH:MM (24 heures).
        message: Contenu du rappel a annoncer a l'echeance.
    """
    now = datetime.now()
    try:
        heure_obj = datetime.strptime(heure, "%H:%M").time()
        cible = datetime.combine(now.date(), heure_obj)
        if cible < now:
            cible += timedelta(days=1)

        def _fin_rappel():
            TIMERS.pop(message, None)
            _notifier(f"Rappel : {message}.")

        t = threading.Timer((cible - now).total_seconds(), _fin_rappel)
        t.daemon = True
        TIMERS[message] = t
        t.start()
        return f"Rappel programme a {heure} pour : '{message}'."
    except ValueError:
        return "Erreur : le format d'heure doit etre HH:MM."


def annuler_rappel(motif: str, **kwargs) -> str:
    """Annule un minuteur ou un rappel actif d'apres son motif ou son contenu.

    Args:
        motif: Le motif du minuteur ou le contenu du rappel, tel qu'indique lors de sa creation.
    """
    t = TIMERS.pop(motif, None)
    if t:
        t.cancel()
        return f"'{motif}' annule."
    return f"Aucun minuteur ou rappel actif ne correspond a '{motif}'."


def lister_rappels(**kwargs) -> str:
    """Liste tous les minuteurs et rappels actuellement actifs."""
    if not TIMERS:
        return "Aucun minuteur ou rappel actif."
    return "Actifs : " + ", ".join(TIMERS)


def calculer(expression: str, **kwargs) -> str:
    """Evalue une expression mathematique simple (addition, soustraction,
    multiplication, division, puissance, parentheses).

    Args:
        expression: L'expression mathematique a calculer, ex : '12 * (3 + 4)'.
    """
    if not re.fullmatch(r"[0-9\.\+\-\*\/\(\)\s]+", expression):
        return "Expression invalide : seuls les nombres et operateurs de base sont autorises."
    try:
        resultat = eval(expression, {"__builtins__": {}}, {})
        return f"Resultat : {resultat}"
    except Exception as e:
        return f"Erreur de calcul : {e}"


def rechercher_fichier(nom: str, **kwargs) -> str:
    """Recherche un fichier par son nom (ou partie de nom) dans le dossier personnel.

    Args:
        nom: Nom, ou partie du nom, du fichier recherche.
    """
    try:
        resultat = subprocess.run(
            ["find", os.path.expanduser("~"), "-iname", f"*{nom}*", "-not", "-path", "*/.*"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        fichiers = [l for l in resultat.stdout.splitlines() if l][:10]
        if not fichiers:
            return f"Aucun fichier trouve pour '{nom}'."
        return "Fichiers trouves : " + " | ".join(fichiers)
    except Exception as e:
        return f"Erreur lors de la recherche du fichier : {e}"


def copier_dans_presse_papier(texte: str, **kwargs) -> str:
    """Copie un texte dans le presse-papiers.

    Args:
        texte: Le texte a copier.
    """
    try:
        subprocess.run(
            ["xclip", "-selection", "clipboard"], input=texte.encode(), check=True
        )
        return "Texte copie dans le presse-papiers."
    except Exception as e:
        return f"Erreur lors de la copie : {e}"


def lire_presse_papier(**kwargs) -> str:
    """Lit le contenu actuel du presse-papiers."""
    try:
        resultat = subprocess.run(
            ["xclip", "-selection", "clipboard", "-o"],
            capture_output=True,
            text=True,
            check=True,
        )
        return resultat.stdout or "Le presse-papiers est vide."
    except Exception as e:
        return f"Erreur lors de la lecture du presse-papiers : {e}"


def prendre_capture_ecran(**kwargs) -> str:
    """Prend une capture d'ecran complete et l'enregistre dans le dossier Images."""
    try:
        dossier = os.path.expanduser("~/Images")
        os.makedirs(dossier, exist_ok=True)
        chemin = os.path.join(
            dossier, f"capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        )
        subprocess.run(["gnome-screenshot", "-f", chemin], check=True)
        return f"Capture d'ecran enregistree dans {chemin}."
    except Exception as e:
        return f"Erreur lors de la capture d'ecran : {e}"
        
def envoyer_notification(titre: str, message: str, **kwargs) -> str:
    """Affiche une notification visuelle sur le bureau.

    Args:
        titre: Titre de la notification.
        message: Contenu de la notification.
    """
    try:
        subprocess.run(["notify-send", titre, message], check=True)
        return "Notification envoyee."
    except Exception as e:
        return f"Erreur lors de l'envoi de la notification : {e}"


def rechercher_sur_le_web(requete: str, **kwargs) -> str:
    """Ouvre une recherche web dans le navigateur par defaut.

    Args:
        requete: Les termes a rechercher.
    """
    try:
        url = f"https://www.google.com/search?q={requests.utils.quote(requete)}"
        webbrowser.open(url)
        return f"Recherche lancee pour : {requete}."
    except Exception as e:
        return f"Erreur lors de la recherche web : {e}"


def ouvrir_site_web(url: str, **kwargs) -> str:
    """Ouvre un site web dans le navigateur par defaut.

    Args:
        url: L'adresse du site a ouvrir (avec ou sans http/https).
    """
    try:
        if not url.startswith("http"):
            url = "https://" + url
        webbrowser.open(url)
        return f"Ouverture du site {url}."
    except Exception as e:
        return f"Erreur lors de l'ouverture du site : {e}"


# ============================================================
# OUTILS - MULTIMEDIA
# ============================================================

async def _async_identify_song():
    WAVE_OUTPUT_FILENAME = "temp_shazam.wav"
    RECORD_SECONDS = "5"

    try:
        print("\n[Ecoute Shazam en cours...]")

        subprocess.run(
            [
                "arecord",
                "-D",
                "default",
                "-f",
                "S16_LE",
                "-r",
                "44100",
                "-c",
                "1",
                "-d",
                RECORD_SECONDS,
                WAVE_OUTPUT_FILENAME,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )

        shazam = Shazam()
        out = await shazam.recognize(WAVE_OUTPUT_FILENAME)

        if "track" in out:
            title = out["track"].get("title", "Inconnu")
            artist = out["track"].get("subtitle", "Inconnu")
            return f"La chanson actuelle est '{title}' de l'artiste '{artist}'."
        else:
            return "Aucune musique n'a pu etre identifiee."

    except Exception as e:
        return f"Erreur lors de la capture du micro ou Shazam : {e}"
    finally:
        if os.path.exists(WAVE_OUTPUT_FILENAME):
            os.remove(WAVE_OUTPUT_FILENAME)


def identify_song(**kwargs) -> str:
    """Identifie la musique jouee aux alentours via Shazam."""
    return asyncio.run(_async_identify_song())


# ============================================================
# COMMANDES RAPIDES LOCALES (sans passer par le LLM)
# ============================================================

def execute_rapide(query: str) -> bool:
    """Traite localement les commandes simples et frequentes (musique, ouverture
    d'applications, arret). Retourne True si une commande a ete
    executee localement, False si le LLM doit prendre le relais.
    """
    q = query.lower()

    # Controle musique
    if any(mot in q for mot in ["musique", "pause", "suivante", "reprend", "suivant", "stop"]):
        if "pause" in q or "stop" in q:
            subprocess.run(["playerctl", "pause"])
            speak("Musique en pause.")
            return True
        if "suivant" in q or "suivante" in q:
            subprocess.run(["playerctl", "next"])
            speak("Titre suivant lance.")
            return True
        if "reprend" in q or "lecture" in q or "relance" in q or "remet" in q:
            subprocess.run(["playerctl", "play"])
            speak("Je relance la lecture.")
            return True

    # Ouverture d'applications
    if "ouvre" in q or "lance" in q or "demarre" in q:
        for nom_app, commande in APPLICATIONS.items():
            if nom_app in q:
                subprocess.Popen(commande)
                speak(f"Lancement de {nom_app}.")
                return True

    # Arret direct de l'assistant
    if any(mot in q for mot in ["au revoir", "eteins-toi", "quitter"]):
        speak("A votre service, Monsieur.")
        os._exit(0)

    return False


# ============================================================
# ENREGISTREMENT DES OUTILS
# ============================================================

AVAILABLE_TOOLS = {
    "get_weather_forecast": get_weather_forecast,
    "get_system_status": get_system_status,
    "get_heure": get_heure,
    "get_date_du_jour": get_date_du_jour,
    "identify_song": identify_song,
    "bluetooth_on": bluetooth_on,
    "bluetooth_off": bluetooth_off,
    "wifi_on": wifi_on,
    "wifi_off": wifi_off,
    "regler_volume": regler_volume,
    "couper_son": couper_son,
    "activer_son": activer_son,
    "regler_luminosite": regler_luminosite,
    "verrouiller_ecran": verrouiller_ecran,
    "mettre_en_veille": mettre_en_veille,
    "fermer_application": fermer_application,
    "create_manim_animation": create_manim_animation,
    "creer_minuteur": creer_minuteur,
    "programmer_rappel": programmer_rappel,
    "annuler_rappel": annuler_rappel,
    "lister_rappels": lister_rappels,
    "calculer": calculer,
    "rechercher_fichier": rechercher_fichier,
    "copier_dans_presse_papier": copier_dans_presse_papier,
    "lire_presse_papier": lire_presse_papier,
    "prendre_capture_ecran": prendre_capture_ecran,
    "envoyer_notification": envoyer_notification,
    "rechercher_sur_le_web": rechercher_sur_le_web,
    "ouvrir_site_web": ouvrir_site_web,
    "obtenir_adresse_ip": obtenir_adresse_ip,
    "lister_processus_gourmands": lister_processus_gourmands,
}

tools_list = list(AVAILABLE_TOOLS.values())


def construire_dates_utiles() -> str:
    """Construit la liste des dates relatives utiles (aujourd'hui, demain, etc.)."""
    now = datetime.now()
    jours_fr = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

    dates_utiles = [
        f"- aujourd'hui : {now.strftime('%Y-%m-%d')}",
        f"- demain (ou dans 1 jour) : {(now + timedelta(days=1)).strftime('%Y-%m-%d')}",
        f"- apres-demain (ou dans 2 jours) : {(now + timedelta(days=2)).strftime('%Y-%m-%d')}",
        f"- dans 3 jours : {(now + timedelta(days=3)).strftime('%Y-%m-%d')}",
        f"- dans 4 jours : {(now + timedelta(days=4)).strftime('%Y-%m-%d')}",
        f"- dans 5 jours : {(now + timedelta(days=5)).strftime('%Y-%m-%d')}",
    ]

    for i in range(1, 6):
        future_date = now + timedelta(days=i)
        nom_jour = jours_fr[future_date.weekday()]
        dates_utiles.append(f"- prochain {nom_jour} : {future_date.strftime('%Y-%m-%d')}")

    return "\n".join(dates_utiles)


def construire_instruction_systeme() -> dict:
    """Construit le message systeme envoye au LLM a chaque requete."""
    dates_str = construire_dates_utiles()
    return {
        "role": "system",
        "content": (
            "Assistant vocal factuel. Reponses courtes (3 phrases max), pour lecture a voix haute.\n\n"
            f"CONTEXTE TEMPOREL :\n"
            f"- Il est actuellement {get_heure()}\n\n"
            "METEO (obligatoire, jamais de connaissances internes) :\n"
            "- 1 appel par ville, jamais groupe. Attends chaque resultat avant de repondre.\n"
            "- Base-toi UNIQUEMENT sur `donnees` (aligne a `colonnes`). N'invente rien (phenomene ou jour non demande).\n"
            "- Resume : 1 phrase/jour (min/max + tendance), JAMAIS heure par heure, JAMAIS de puces.\n"
            "- Si `error` renvoye, explique-le tel quel, rien d'autre.\n\n"
            "DATES (copie exacte, ne calcule jamais) :\n"
            f"{dates_str}\n"
            f"- Ville par defaut : {VILLE_PAR_DEFAUT}. Jour par defaut : aujourd'hui.\n"
            "- heure_debut/heure_fin : entiers uniquement. Minuit = jour suivant, heure 0.\n\n"
            "MANIM (animations) :\n"
            "- 'code' : code Python valablement indente (4 espaces par niveau). AUCUNE balise ``` dans l'argument.\n"
            "- 'scene_name' : le nom exact de la classe.\n"
            "- Si le retour d'outil indique une erreur, resume le probleme en 1 seule phrase sans afficher ni lire de code Python.\n"
            "- En cas d'erreur dans les outils, ne genere JAMAIS de code Python dans le chat.\n\n"
            "SYSTEME ET UTILITAIRES :\n"
            "- Pour le volume et la luminosite, le niveau est toujours un entier entre 0 et 100.\n"
            "- Pour l'extinction ou le redemarrage, previens toujours l'utilisateur avant d'appeler l'outil.\n\n"
            "Ne devine jamais : rappelle l'outil si besoin de donnees supplementaires."
        ),
    }


def executer_appel_outil(fn_name: str, args: dict) -> str:
    """Execute un appel d'outil demande par le LLM et retourne le resultat serialise."""
    if fn_name in AVAILABLE_TOOLS:
        try:
            result = AVAILABLE_TOOLS[fn_name](**args)
        except Exception as e:
            result = {"error": f"Erreur : {e}"}
    else:
        result = {"error": f"Outil inconnu : {fn_name}"}

    return json.dumps(result, ensure_ascii=False) if isinstance(result, dict) else str(result)


# ============================================================
# BOUCLE PRINCIPALE
# ============================================================

def boucle_principale() -> None:
    while True:
        try:
            question = input("\nPosez votre question (ou 'quitter') : ")
            t0 = time.perf_counter()
            if question.lower() in ["quitter", "exit"]:
                break
 
            # 1. Verification rapide (musique, applications, arret)
            if execute_rapide(question):
                continue
 
            # 2. Construction du contexte systeme et envoi au LLM
            messages = [construire_instruction_systeme(), {"role": "user", "content": question}]
 
            for _ in range(MAX_ETAPES_OUTILS):
                response = chat(
                    model=MODEL_NAME,
                    messages=messages,
                    tools=tools_list,
                    think=False,
                    keep_alive="30m",
                    options={"num_predict": 300},
                )
 
                messages.append(response.message)
                print(f"[{time.perf_counter() - t0:.2f} s depuis la question]")


                if not response.message.tool_calls:
                    speak(response.message.content)
                    break

                for call in response.message.tool_calls:
                    tool_content = executer_appel_outil(call.function.name, call.function.arguments)
                    messages.append(
                        {"role": "tool", "name": call.function.name, "content": tool_content}
                    )
            else:
                speak("Je n'ai pas reussi a traiter votre demande, pouvez-vous reformuler ?")

        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    boucle_principale()

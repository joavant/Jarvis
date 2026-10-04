import csv
import json
import os
from datetime import datetime, timedelta, timezone
import ollama
import requests
from dotenv import load_dotenv

# --- 1. Configuration Initiale ---
load_dotenv()
OPENWEATHER_APP_ID = os.getenv("OPENWEATHER_APP_ID")
if not OPENWEATHER_APP_ID:
    raise SystemExit(
        "Erreur : la variable d'environnement OPENWEATHER_APP_ID est introuvable."
    )

MODEL = "###" # Si ce code est main alors il peux donner directment la météo
CSV_FILE = "meteo.csv"
FIELDNAMES = ["Date/Heure", "Température", "Description", "Humidité", "Ville"]
DEFAULT_CITY = "#" #Votre ville


# --- 2. Gestion du Cache Local ---
def _ensure_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=FIELDNAMES).writeheader()


def reset_weather_cache():
    """Supprime le cache CSV existant s'il ne date pas d'aujourd'hui, et le
    recrée vide. Si le cache a déjà été régénéré aujourd'hui, on le garde
    tel quel pour éviter de re-télécharger inutilement à chaque lancement.
    """
    if os.path.exists(CSV_FILE):
        derniere_maj = datetime.fromtimestamp(os.path.getmtime(CSV_FILE)).date()
        aujourdhui = datetime.now().date()

        if derniere_maj == aujourdhui:
            # Le cache a déjà été régénéré aujourd'hui : on ne le touche pas
            return

        os.remove(CSV_FILE)

    _ensure_csv()


def _read_cache(city: str, date_fr: str):
    """Lit les lignes du CSV pour une ville et une date (format dd/mm/yyyy)."""
    _ensure_csv()
    rows = []
    with open(CSV_FILE, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ville = (row.get("Ville") or "").strip().title()
            date_heure = (row.get("Date/Heure") or "")
            if ville == city and date_heure.startswith(date_fr):
                rows.append(row)
    return rows


def _fetch_and_cache(city: str):
    """Récupère les prévisions 5 jours (API) et met à jour le cache CSV."""
    city = city.strip().title()
    url = "http://api.openweathermap.org/data/2.5/forecast"
    params = {
        "q": city,
        "appid": OPENWEATHER_APP_ID,
        "units": "metric",
        "lang": "fr",
    }
    res = requests.get(url, params=params, timeout=10)
    if res.status_code != 200:
        return None, f"Erreur API ou ville introuvable (code {res.status_code})."

    try:
        data = res.json()
        forecast_list = data["list"]
        city_tz_offset = data.get("city", {}).get("timezone", 0)
    except (ValueError, KeyError):
        return None, "Réponse API inattendue."

    _ensure_csv()

    cache = {}
    with open(CSV_FILE, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ville = (row.get("Ville") or "").strip().title()
            date_heure = (row.get("Date/Heure") or "").strip()
            cache[(ville, date_heure)] = row

    cache = {k: v for k, v in cache.items() if k[0] != city}

    for entry in forecast_list:
        try:
            dt_utc = entry["dt"]
            utc_dt = datetime.fromtimestamp(dt_utc, tz=timezone.utc)
            local_dt = (utc_dt + timedelta(seconds=city_tz_offset)).replace(tzinfo=None)
            date_heure_str = local_dt.strftime("%d/%m/%Y %H:%M")

            cache[(city, date_heure_str)] = {
                "Date/Heure": date_heure_str,
                "Température": entry["main"]["temp"],
                "Description": entry["weather"][0]["description"],
                "Humidité": entry["main"]["humidity"],
                "Ville": city,
            }
        except (KeyError, IndexError, TypeError):
            continue

    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(cache.values())

    return True, None


# --- 3. L'Outil Central ---
def get_weather_forecast(city: str = DEFAULT_CITY, date: str = None, heure_debut=0, heure_fin=23, **kwargs) -> dict:
    """Récupère la météo et filtre les heures selon la demande."""
    city_normalized = (city or DEFAULT_CITY).strip().title() or DEFAULT_CITY

    try:
        val_debut = kwargs.get("start_time", heure_debut)
        h_debut = int(str(val_debut).split(":")[0])
        val_fin = kwargs.get("end_time", heure_fin)
        h_fin = int(str(val_fin).split(":")[0])
    except Exception:
        h_debut, h_fin = 0, 23

    overnight = h_debut > h_fin

    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    try:
        date_obj = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return {"error": f"Format de date invalide : '{date}'. Format attendu: YYYY-MM-DD."}

    today = datetime.now().date()
    if date_obj.date() < today:
        return {"error": "Date dans le passé : l'API ne fournit que les prévisions à venir."}
    if (date_obj.date() - today).days > 5:
        return {"error": "Date hors limite. L'API est limitée aux 5 prochains jours."}

    date_fr = date_obj.strftime("%d/%m/%Y")

    rows = _read_cache(city_normalized, date_fr)
    if not rows:
        ok, err = _fetch_and_cache(city_normalized)
        if not ok:
            return {"error": err}
        rows = _read_cache(city_normalized, date_fr)

    if not rows:
        return {"error": f"Aucune donnée pour {city_normalized} le {date_fr}."}

    COLONNES = ["Heure", "Température (°C)", "Description", "Humidité (%)"]

    lignes = []
    for r in rows:
        date_heure = (r.get("Date/Heure") or "")
        try:
            heure_str = date_heure.split(" ")[1]
            heure_int = int(heure_str.split(":")[0])
        except (IndexError, ValueError):
            continue

        if overnight:
            if heure_int >= h_debut or heure_int <= h_fin:
                lignes.append((heure_int, heure_str, r))
        else:
            if h_debut <= heure_int <= h_fin:
                lignes.append((heure_int, heure_str, r))

    lignes.sort(key=lambda x: x[0])

    donnees = []
    for _, heure_str, r in lignes:
        donnees.append([
            heure_str,
            r.get("Température", ""),
            r.get("Description", ""),
            r.get("Humidité", ""),
        ])

    if not donnees:
        return {"error": f"Aucune donnée trouvée pour la plage {h_debut}h-{h_fin}h."}

    return {
        "city": city_normalized,
        "date": date_fr,
        "plage_horaire": f"De {h_debut}h à {h_fin}h",
        "colonnes": COLONNES,
        "donnees": donnees,
    }


# --- 4. Définition pour l'IA ---
TOOLS_SCHEMA = [{
    "type": "function",
    "function": {
        "name": "get_weather_forecast",
        "description": "Retourne la météo horaire. Utilise heure_debut et heure_fin (entiers) pour filtrer les heures.",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "Nom de la ville. Par défaut #### si non précisé."}, #Mettre votre ville
                "date": {"type": "string", "description": "Date YYYY-MM-DD tirée de la table."},
                "heure_debut": {"type": "integer", "description": "Heure de début (ex: 6)."},
                "heure_fin": {"type": "integer", "description": "Heure de fin (ex: 21)."}
            },
            "required": ["date"],
        },
    },
}]


# --- 5. Prompt Système Dynamique ---
def generate_system_prompt() -> str:
    now = datetime.now()
    jours_fr = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

    dates_utiles = [
        f"- aujourd'hui : {now.strftime('%Y-%m-%d')}",
        f"- demain (ou dans 1 jour) : {(now + timedelta(days=1)).strftime('%Y-%m-%d')}",
        f"- après-demain (ou dans 2 jours) : {(now + timedelta(days=2)).strftime('%Y-%m-%d')}",
        f"- dans 3 jours : {(now + timedelta(days=3)).strftime('%Y-%m-%d')}",
        f"- dans 4 jours : {(now + timedelta(days=4)).strftime('%Y-%m-%d')}",
        f"- dans 5 jours : {(now + timedelta(days=5)).strftime('%Y-%m-%d')}"
    ]

    for i in range(1, 6):
        future_date = now + timedelta(days=i)
        nom_jour = jours_fr[future_date.weekday()]
        dates_utiles.append(f"- prochain {nom_jour} : {future_date.strftime('%Y-%m-%d')}")

    dates_str = "\n".join(dates_utiles)

    return (
        "Tu es un assistant météo francophone précis. Utilise toujours la ville de Marseille si aucune ville n'est indiquée. "
        "Si aucun jour n'est indiqué, utilise AUJOURD'HUI.\n\n"
        "Pour obtenir la météo, tu DOIS utiliser l'outil `get_weather_forecast`.\n\n"
        "Voici la table STRICTE de correspondance des dates :\n"
        f"{dates_str}\n\n"
        "RÈGLES ABSOLUES :\n"
        "1. Copie/colle la date YYYY-MM-DD exacte de cette table. Ne fais AUCUN calcul de date toi-même.\n"
        "2. N'invente JAMAIS d'arguments non prévus. Pour filtrer l'heure, utilise UNIQUEMENT `heure_debut` et `heure_fin` "
        "en tant qu'entiers (ex: 6 pour 6h, 14 pour 14h). Si l'utilisateur demande 'minuit', utilise la date du jour suivant "
        "avec l'heure 0. Si aucune ville n'est précisée, utilise city='Marseille'.\n"
        "3. Le résultat de l'outil contient `colonnes` (les noms des colonnes) et `donnees` (les lignes). "
        "La i-ème valeur de chaque ligne correspond à la i-ème colonne. Les heures sont en heure locale de la ville.\n"
        "4. Rédige ensuite ta réponse finale naturellement en français, en te basant UNIQUEMENT sur les données renvoyées par l'outil. "
        "N'invente aucune valeur, aucune unité."
    )


# --- 6. Moteur Principal ---
def run_assistant(user_prompt: str) -> str:
    messages = [
        {"role": "system", "content": generate_system_prompt()},
        {"role": "user", "content": user_prompt}
    ]

    for step in range(5):
        response = ollama.chat(model=MODEL, messages=messages, tools=TOOLS_SCHEMA)
        message = response.get("message", {})
        messages.append(message)

        tool_calls = message.get("tool_calls")

        if not tool_calls:
            return message.get("content", "Aucune réponse texte générée.")

        for call in tool_calls:
            name = call["function"]["name"]

            raw_args = call["function"].get("arguments", {})
            if isinstance(raw_args, str):
                try:
                    raw_args = json.loads(raw_args)
                except json.JSONDecodeError:
                    raw_args = {}
            if isinstance(raw_args, dict) and "arguments" in raw_args and isinstance(raw_args["arguments"], dict):
                args = raw_args["arguments"]
            elif isinstance(raw_args, dict):
                args = raw_args
            else:
                args = {}

            print(f"🔧 [Outil appelé] {name} | Arguments : {args}")

            if name == "get_weather_forecast":
                try:
                    result = get_weather_forecast(**args)
                except TypeError as e:
                    result = {"error": f"Mauvais paramètres envoyés : {e}. Utilise uniquement city, date, heure_debut, heure_fin."}
                except Exception as e:
                    result = {"error": f"Erreur inattendue : {str(e)}"}
            else:
                result = {"error": f"Outil inconnu : {name}"}

            messages.append({
                "role": "tool",
                "name": name,
                "content": json.dumps(result, ensure_ascii=False),
            })

    return "Désolé, je n'ai pas réussi à obtenir une réponse stable après 5 étapes (boucle infinie d'outils)."


if __name__ == "__main__":
    try:
        reset_weather_cache()
        user_input = input("Que veux-tu savoir sur la météo ? : ")
        print("\n⏳ Recherche en cours...\n")
        reponse = run_assistant(user_input)
        print(f"\n🌤️ [RÉPONSE IA]\n{reponse}")
    except KeyboardInterrupt:
        print("\nFin du programme.")

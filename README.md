# Project J.A.R.V.I.S. (Just A Rather Very Intelligent System)

J.A.R.V.I.S. est un assistant domestique inspiré de l'univers Marvel, pensé pour Linux (GNOME). Un LLM local tourne via Ollama, appelle des outils (tool calling) pour piloter l'ordinateur, puis répond à voix haute avec Piper TTS. Rien n'est envoyé dans le cloud, hors météo et IP publique.

## Fonctionnalités

- **Tool calling local** : le LLM (Ollama) choisit et enchaîne les outils, jusqu'à 6 étapes par demande (garde-fou anti-boucle).
- **Commandes rapides** : musique, ouverture d'applications et arrêt sont traités sans passer par le LLM, donc instantanément.
- **Synthèse vocale** : voix française *Piper*, lecture directe via `sounddevice`.
- **Météo** : prévisions horaires sur 5 jours (OpenWeather) avec cache CSV régénéré chaque jour.
- **Shazam** : identifie la musique ambiante via le micro (5 secondes d'écoute).
- **Mesure de latence** : le temps écoulé depuis la question est affiché après chaque appel au modèle.

### Outils disponibles

| Catégorie | Outils |
|---|---|
| Informations | heure, date, état du système (CPU, batterie, températures), adresse IP locale et publique, top 5 des processus CPU |
| Connectivité | Bluetooth on/off, Wi-Fi on/off |
| Son et écran | volume, mute/unmute, luminosité, verrouillage, mise en veille |
| Applications | fermer une application, ouvrir un site web, recherche Google |
| Productivité | minuteurs, rappels à heure fixe (annulation et liste), calculatrice, recherche de fichier, presse-papiers (lecture/copie), capture d'écran, notification de bureau |
| Multimédia | identification Shazam, contrôle de la musique (pause, reprise, titre suivant) |
| Météo | prévisions par ville, date et plage horaire |

### Commandes rapides locales

- **Musique** : "pause" ou "stop", "suivant", "reprends" (via `playerctl`).
- **Applications** : "ouvre / lance / démarre" suivi de navigateur, terminal, invite de commande, calculatrice, documents, fichiers, éditeur de texte ou spotify.
- **Arrêt** : "quitter", "au revoir" ou "eteins-toi".

## Structure du projet

| Fichier | Rôle |
|---|---|
| `jarvisv7.py` | Boucle principale, enregistrement des outils, prompt système, commandes rapides |
| `importmeteo.py` | Outil météo (API OpenWeather + cache `meteo.csv`), utilisable aussi seul |
| `voice.py` | Synthèse vocale Piper : `speak(texte)` |

## Installation

### 1. Prérequis

- Linux avec GNOME (Ubuntu, Linux Mint...) et Python 3.10+
- [Ollama](https://ollama.ai/) avec un modèle qui **supporte les tools**. Vérifiez la ligne `tools` dans les capacités avec `ollama show <modele>`.
- [Piper TTS](https://github.com/rhasspy/piper) et une voix française (fichiers `.onnx` et `.onnx.json`)
- Une clé API [OpenWeather](https://openweathermap.org/api)

Outils système utilisés :

```bash
sudo apt install bluez rfkill network-manager pulseaudio-utils brightnessctl playerctl xclip gnome-screenshot libnotify-bin alsa-utils gnome-terminal gnome-calculator nautilus gedit
```

### 2. Clonage et dépendances

```bash
git clone https://github.com/joavant/Jarvis.git
cd Jarvis
python3 -m venv venv
source venv/bin/activate
pip install psutil requests python-dotenv ollama shazamio piper-tts sounddevice numpy manim
```

### 3. Modèle Ollama

```bash
ollama pull qwen3:1.7b
```

Le modèle se change avec `MODEL_NAME` dans `jarvisv7.py`. Un modèle sans support des tools provoque l'erreur `does not support tools (status code: 400)`.

### 4. Configuration

Créez un fichier `.env` à la racine du projet :

```
OPENWEATHER_APP_ID=votre_cle_api
```

Renseignez ensuite vos valeurs dans le code :

| Fichier | Variable | Description |
|---|---|---|
| `jarvisv7.py` | `BLUETOOTH_MAC` | Adresse MAC de votre adaptateur Bluetooth |
| `jarvisv7.py` | `VILLE_PAR_DEFAUT` | Ville utilisée si aucune n'est précisée |
| `importmeteo.py` | `DEFAULT_CITY` | Ville par défaut du module météo |
| `voice.py` | `MODEL_PATH`, `CONFIG_PATH` | Chemins du modèle Piper `.onnx` et de son `.onnx.json` |

## Utilisation

```bash
python3 jarvisv7.py
```

Tapez votre demande à l'invite, par exemple :

- "Active le bluetooth puis ouvre le site ....."
- "Quelle est la météo à Lyon demain entre 8h et 18h ?"
- "Mets un minuteur de 10 minutes pour les pâtes"
- "Règle le volume à 40"

Tapez `quitter` pour arrêter. Le module météo se teste aussi seul :

```bash
python3 importmeteo.py
```

## Notes

- La météo est limitée aux 5 prochains jours (limite de l'API gratuite). Le cache `meteo.csv` est vidé au premier lancement de chaque jour.
- Un minuteur et un rappel portant le même libellé s'écrasent mutuellement.

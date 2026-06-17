# Project J.A.R.V.I.S. (Just A Rather Very Intelligent System)

J.A.R.V.I.S. est un assistant personnel intelligent et multimodal inspiré de l'univers Marvel. Il combine reconnaissance vocale, vision par ordinateur, analyse musicale (Shazam) et une base de connaissances personnalisée (RAG).



## ✨ Fonctionnalités

- **Reconnaissance Vocale Offline** : Utilise *Vosk* pour une écoute continue sans envoyer de données dans le cloud.
- **Cerveau RAG (Retrieval-Augmented Generation)** : Capacité d'apprendre à partir de tes propres PDF, documents Word et URLs via *ChromaDB* et *Ollama*.
- **Vision Artificielle** : Reconnaissance faciale et comptage de personnes en temps réel avec *OpenCV*.
- **Multimédia** : Intégration de *Shazam* pour identifier la musique ambiante et contrôle complet de *Spotify*.
- **Météo & Système** : Rapports météo en temps réel (OpenWeather) et monitoring des ressources du PC (CPU, Batterie).
- **Interface Futuriste** : HUD interactif développé en HTML/JS intégré dans une fenêtre *PyQt5* transparente.

## Installation

### 1. Prérequis
- Python 3.10+
- [Ollama](https://ollama.ai/) (avec le modèle `gemma2:2b`)
- [Piper TTS](https://github.com/rhasspy/piper) pour la synthèse vocale.
- Un modèle Vosk à placer dans le dossier `/model`.

### 2. Clonage et dépendances
```bash
git clone [https://github.com/joavant/Jarvis.git](https://github.com/joavant/Jarvis.git)
cd Jarvis
pip install -r requirements.txt
```

### Lancez d'abord le script de connaissance pour indexer vos documents Option 4:
```bash

python rag4.py
```

Lancez l'assistant principal :
```bash

python jarvis6_1.py
```

# Visualiser la base de donné
1. Lancez la commande 
```bash
python3 co-occurence.py
```
2. Lancez cette commande
```bash
python3 -m http.server 8000
```
3. puis, sur un navigateur faites
```bash
http://0.0.0.0:8000/nom_du_fichier_html
```
## Démo en ligne (Exemple avec 4 nœuds)

Tu peux explorer la base de connaissances directement depuis ton navigateur grâce aux deux modes de visualisation disponibles :

* **[Lancer la version 2D (Plus fluide et rapide)](https://joavant.github.io/Jarvis/cortex2d.html)**
* **[Lancer la version 3D](https://joavant.github.io/Jarvis/cortex3d.html)**

> 💡 *Note : Personnellement, l'affichage reste fluide en local jusqu'à 12 975 nœuds et 56 982 liens avec les paramètres par défaut.*

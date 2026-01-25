import os, sys, threading, subprocess, json, time, psutil, requests, wave, asyncio
import numpy as np
import pyaudio
import chromadb, ollama
from shazamio import Shazam
from sentence_transformers import SentenceTransformer
from PyQt5.QtCore import QUrl, Qt, pyqtSignal, QObject, QTimer, pyqtSlot
from PyQt5.QtWidgets import QApplication, QMainWindow
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWebChannel import QWebChannel
from vosk import Model, KaldiRecognizer
import warnings
import cv2
import socket, re
import librosa
from dotenv import load_dotenv
from scipy.spatial.distance import cosine

# --- CONFIGURATION ---
load_dotenv()
warnings.filterwarnings("ignore")
OPENWEATHER_APP_ID = os.getenv("OPENWEATHER_APP_ID")
current_people_count = 0
last_seen_names = []
subjects = ["", "Joachim", "Famille", "Ami"] # 1=Joachim, 2=Famille, 3=Ami
mic_busy = threading.Event()
voice_profiles = {}
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100
RECORD_SECONDS = 10  # Durée de l'enregistrement en secondes
WAVE_OUTPUT_FILENAME = "output.wav"

class Config:
    PIPER_MODEL = "fr_FR-siwis-low.onnx"
    LLM_FAST = "gemma2:2b"
    EMBED_MODEL = 'all-MiniLM-L6-v2'
    DB_PATH = os.getenv("DB_PATH")
    VOSK_MODEL_PATH = "model"

# --- LOGIQUE DE COMMANDES ---
def execute_local(query, bridge):
    q = query.lower()
    
    if "heure" in q:
        speak(f"Il est précisément {time.strftime('%H heures %M')}.", bridge)
        return True

    if any(x in q for x in ["système", "batterie", "processeur"]):
        battery = psutil.sensors_battery()
        cpu = psutil.cpu_percent()
        msg = f"Processeur à {cpu}%. "
        if battery: msg += f"Batterie à {battery.percent}%."
        speak(msg, bridge)
        return True

    if any(x in q for x in ["qui est là", "combien de personnes"]):
        noms = ", ".join(last_seen_names) if last_seen_names else "personne de connu"
        speak(f"Je vois {current_people_count} personne(s). Identification : {noms}.", bridge)
        return True

    if "shazam" in q or "reconnais" in q:
        speak("Bien Monsieur, j'écoute la musique.", bridge)
        threading.Thread(target=lambda: asyncio.run(recognize_from_mic())).start()        
        # On lance dans un nouveau thread pour ne pas bloquer l'interface
        return True

    if "favoris" in q or "ma musique" in q:
        check_spotify_silent()
        # Ton URI spécifique pour tes titres likés
        uri = "spotify:user:31mjg5pq63x4kuzfipvpq3iwv3pq:collection"
        try:
            # On utilise spotify-cli pour charger l'URI
            subprocess.run(["spotify-cli", "play", "--uri", uri], check=True)
            speak("Je lance vos titres favoris, Monsieur.", bridge)
        except:
            speak("Je n'ai pas pu charger vos favoris.", bridge)
        return True

    if any(x in q for x in ["apprends ma voix", "enregistre ma voix", "je m'appelle"]):
        speak("Très bien Monsieur. Veuillez saisir votre prénom dans la console pour valider l'empreinte.", bridge)
        
        # Le programme va s'arrêter ici et attendre ton entrée dans le terminal
        print("\n" + "="*30)
        new_name = input(" SYSTÈME : Entrez le prénom à enregistrer : ").strip().capitalize()
        print("="*30 + "\n")

        if new_name:
            # On utilise l'audio_np qui vient d'être capté par la boucle
            # (Note : Assure-toi que audio_np est accessible dans tes arguments)
            save_voice_profile(new_name, audio_np)
            speak(f"C'est enregistré. Je vous reconnais maintenant sous le nom de {new_name}.", bridge)
        else:
            speak("Annulation de l'enregistrement.", bridge)
        
        return True

    if "météo" in q or "marseille" in q:
        try:
            res = requests.get(f"http://api.openweathermap.org/data/2.5/weather?q=Marseille&appid={OPENWEATHER_APP_ID}&units=metric&lang=fr").json()
            speak(f"Monsieur, il fait {round(res['main']['temp'])} degrés à Marseille.", bridge)
        except: speak("Erreur météo.", bridge)
        return True

    if "bluetooth" in q or "active" in q:
        speak("J'active le bluetooth", bridge)
        bluetooth()
        return True

    if any(x in q for x in ["musique", "pause", "suivante", "reprend", "suivant", "stop"]):
        try:
            if "pause" in q or "stop" in q:
                subprocess.run(["playerctl", "pause"])
                speak("Musique en pause.", bridge)
            elif "suivante" in q or "suivant" in q:
                subprocess.run(["playerctl", "next"])
                time.sleep(0.5)
                info = get_track_info()
                speak(f"Titre suivant : {info if info else 'lancé'}.", bridge)
            elif "reprend" in q or "musique" in q:
                subprocess.run(["playerctl", "play"])
                speak("Je relance la lecture.", bridge)
        except: speak("Aucun lecteur actif.", bridge)
        return True

    if any(x in q for x in ["titre", "chante"]):
        info = get_track_info()
        speak(f"Il s'agit de {info}." if info else "Je ne vois aucun titre en cours.", bridge)
        return True

    if "mélange" in q or "aléatoire" in q:
        subprocess.run(["spotify-cli", "shuffle", "on"])
        speak("Mode aléatoire activé.", bridge)
        return True

    if "volume" in q or "son" in q:
        if any(x in q for x in ["monte", "augmente", "fort"]):
            os.system("amixer set Master 10%+")
            speak("Volume augmenté.", bridge)
        elif any(x in q for x in ["baisse", "diminue"]):
            os.system("amixer set Master 10%-")
            speak("Volume baissé.", bridge)
        return True

    if "ouvre" in q:
        '''if speaker_name.lower() != "joachim":
            speak("Accès refusé.")
            return True'''
        
        target = q.split("ouvre")[-1].strip()

        # DOSSIERS (On vérifie juste si le mot est dans la phrase)
        if "document" in target: # Capte document et documents
            speak("Ouverture des documents.", bridge)
            subprocess.Popen(["xdg-open", os.path.expanduser("~/Documents")])
        elif "téléchargement" in target:
            speak("Ouverture des téléchargements.", bridge)
            subprocess.Popen(["xdg-open", os.path.expanduser("~/Téléchargements")])
        elif "image" in target:
            speak("Ouverture des images.", bridge)
            subprocess.Popen(["xdg-open", os.path.expanduser("~/Images")])

        # APPLICATIONS
        elif "invite" in target or "vite" in target or "terminal" in target:
            speak("Ouverture du terminal.", bridge)
            subprocess.Popen(["gnome-terminal"])
        elif "navigateur" in target or "firefox" in target:
            speak("Lancement de Firefox.", bridge)
            subprocess.Popen(["firefox"])
        elif "calculatrice" in target:
            speak("Lancement de calculatrice.", bridge)
            subprocess.Popen(["gnome-calculator"])
        elif "éditeur" in target or "texte" in target:
            speak("Ouverture de l'éditeur.", bridge)
            # On essaie gnome-text-editor, sinon gedit
            try:
                subprocess.Popen(["gnome-text-editor"])
            except:
                subprocess.Popen(["gedit"])

        # TENTATIVE GÉNÉRIQUE
        else:
            try:
                subprocess.Popen([target])
                speak(f"Lancement de {target}.", bridge)
            except:
                speak(f"Désolé Monsieur, je ne connais pas d'application nommée {target}.", bridge)
        return True

    if any(x in q for x in ["au revoir", "éteins-toi", "quitter"]):
        speak("À votre service, Monsieur.", bridge)
        ollama.generate(model=Config.LLM_FAST, prompt="", keep_alive=0)
        os._exit(0)

    return False

# --- CERVEAU ---
class NexusBrain:
    def __init__(self):
        self.embedder = SentenceTransformer(Config.EMBED_MODEL)
        self.client = chromadb.PersistentClient(path=Config.DB_PATH)

    def process(self, question, bridge):
        if execute_local(question, bridge):
            return None
            
        try:
            col = self.client.get_or_create_collection(name="DIVERS")
            qv = self.embedder.encode(question).tolist()
            results = col.query(query_embeddings=[qv], n_results=2)
            context = "\n".join(results['documents'][0]) if results['documents'] else ""
            
            prompt = f"[SYSTEM: Tu es J.A.R.V.I.S., ton ton est calme et factuel.] CONTEXTE: {context} QUESTION: {question}"
            resp = ollama.generate(model=Config.LLM_FAST, prompt=prompt)['response']
            return resp
        except Exception as e:
            print(f"Erreur Brain: {e}", bridge)
            return "Système instable. En attente de reconnexion."

brain = NexusBrain()

#---Fonctionalitées-----
async def recognize_from_mic():
    mic_busy.set()  # On bloque Vosk
    audio = pyaudio.PyAudio()
    
    try:
        print("[SHAZAM] Début de l'écoute...")
        print("Lancement de Shazam", bridge)
        stream = audio.open(format=FORMAT, channels=CHANNELS, rate=RATE, 
                          input=True, frames_per_buffer=CHUNK)

        frames = []
        # Enregistrement
        for _ in range(0, int(RATE / CHUNK * RECORD_SECONDS)):
            data = stream.read(CHUNK, exception_on_overflow=False)
            frames.append(data)

        stream.stop_stream()
        stream.close()

        # Sauvegarde temporaire
        with wave.open(WAVE_OUTPUT_FILENAME, 'wb') as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(audio.get_sample_size(FORMAT))
            wf.setframerate(RATE)
            wf.writeframes(b''.join(frames))

        # Reconnaissance
        shazam = Shazam()
        out = await shazam.recognize(WAVE_OUTPUT_FILENAME)

        if 'track' in out:
            track = out['track']
            title = track.get('title')
            artist = track.get('subtitle')
            speak(f"J'ai trouvé : {title} de {artist}", bridge)
        else:
            speak("Désolé Monsieur, je n'ai pas pu identifier ce titre.", bridge)

    except Exception as e:
        print(f"Erreur Shazam: {e}")
    finally:
        audio.terminate()
        mic_busy.clear() # On libère le micro pour Vosk

def check_spotify_silent():
    # 1. Vérifier si Spotify tourne déjà
    is_running = any("spotify" in p.name().lower() for p in psutil.process_iter(attrs=['name']))
    
    if not is_running:
        print("Lancement de Spotify en mode caché...")
        with open(os.devnull, 'w') as fnull:
            # Lancement du processus
            subprocess.Popen(["spotify"], stdout=fnull, stderr=fnull, preexec_fn=os.setpgrp)
        
        # 2. Attendre que la fenêtre apparaisse (max 10 secondes)
        # On cherche une fenêtre qui s'appelle "Spotify"
        for _ in range(20): # 20 itérations de 0.5s
            time.sleep(0.5)
            # On essaie de minimiser la fenêtre avec wmctrl
            # -b add,hidden : minimise la fenêtre
            # -i -r : cherche par ID (plus stable) ou par nom
            result = subprocess.run(["wmctrl", "-r", "Spotify", "-b", "add,hidden"], 
                                    stderr=subprocess.DEVNULL)
            
            # Si wmctrl a réussi (code 0), la fenêtre a été trouvée et cachée
            if result.returncode == 0:
                print("Fenêtre Spotify détectée et masquée.")
                break
    else:
        print("Spotify est déjà lancé.")

def save_voice_profile(name, audio_np):
    global voice_profiles
    # Extraction des MFCC (l'empreinte vocale)
    y = audio_np.astype(np.float32) / 32768.0
    mfccs = librosa.feature.mfcc(y=y, sr=16000, n_mfcc=20)
    feat = np.mean(mfccs.T, axis=0)
    
    voice_profiles[name] = feat
    
    # Sauvegarde physique
    serializable = {k: v.tolist() for k, v in voice_profiles.items()}
    with open(DB_FILE, "w") as f:
        json.dump(serializable, f)

def load_profiles():
    global voice_profiles
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            profiles = json.load(f)
            voice_profiles = {name: np.array(feat) for name, feat in profiles.items()}

def bluetooth():
    status = subprocess.run(["bluetoothctl", "show"], capture_output=True, text=True).stdout
    
    if "Powered: yes" not in status:
        print("Activation du Bluetooth...")
        subprocess.run(["bluetoothctl", "power", "on"])
    else:
        print("Le Bluetooth est déjà actif.")

def set_spotify_volume(level):
    """ level: 0.0 à 1.0 """
    try:
        subprocess.run(["playerctl", "volume", str(level)], check=True, stderr=subprocess.DEVNULL)
    except:
        pass

def get_track_info():
    try:
        # Récupère Titre - Artiste
        title = subprocess.check_output("playerctl metadata --format '{{ title }} - {{ artist }}'", shell=True).decode('utf-8').strip()
        # Récupère la position et la durée pour le % de la barre
        pos = float(subprocess.check_output("playerctl position", shell=True).decode('utf-8'))
        length = float(subprocess.check_output("playerctl metadata mpris:length", shell=True).decode('utf-8')) / 1000000
        status = subprocess.check_output("playerctl status", shell=True).decode('utf-8').strip()
        
        progress = (pos / length) * 100 if length > 0 else 0
        return {"title": title, "progress": progress, "status": status}
    except:
        return {"title": "Offline", "progress": 0, "status": "Stopped"}

# --- BRIDGE (Communication avec HTML) ---
class JarvisBridge(QObject):
    gui_update = pyqtSignal(str)

    def send(self, data):
        self.gui_update.emit(json.dumps(data))

    @pyqtSlot(str)
    def receive_text(self, text):
        if text.startswith("MUSIC_CMD:"):
            cmd = text.split(":")[1]
            if cmd == "play-pause":
                subprocess.run("playerctl play-pause", shell=True)
            elif cmd == "next":
                subprocess.run("playerctl next", shell=True)
            elif cmd == "previous":
                subprocess.run("playerctl previous", shell=True)
            return
        """Reçoit le texte du champ input HTML"""
        print(f"Clavier: {text}")
        threading.Thread(target=self._async_process, args=(text,), daemon=True).start()

    def _async_process(self, text):
        response = brain.process(text, self)
        if response:
            speak(response, self)

def speak(text, bridge=None):
    if not text: return
    if bridge:
        bridge.send({"type": "jarvis_msg", "content": text})
    
    clean_text = text.replace('*', '').replace('"', ' ')
    cmd = f'echo "{clean_text}" | piper --model {Config.PIPER_MODEL} --length_scale 1.1 --output_raw | aplay -r 22050 -f S16_LE -t raw 2>/dev/null'
    subprocess.Popen(cmd, shell=True)

# --- UI ---
class JarvisUI(QMainWindow):
    def __init__(self, bridge):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(100, 100, 600, 800)
        
        self.bridge = bridge
        self.bridge.gui_update.connect(self.update_js)
        
        # Setup Canal de communication
        self.channel = QWebChannel()
        self.channel.registerObject("backend", self.bridge)
        
        self.browser = QWebEngineView()
        self.browser.page().setWebChannel(self.channel)
        self.browser.page().setBackgroundColor(Qt.transparent)
        
        path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "hud2.html")
        self.browser.setUrl(QUrl.fromLocalFile(path))
        self.setCentralWidget(self.browser)
        
        self.stats_timer = QTimer()
        self.stats_timer.timeout.connect(self.push_stats)
        self.stats_timer.start(1000)

    def update_js(self, json_str):
        self.browser.page().runJavaScript(f"window.processPythonData({json_str});")

    def push_stats(self):
        bat = psutil.sensors_battery()
        self.bridge.send({
            "type": "stats", 
            "cpu": psutil.cpu_percent(), 
            "memory": psutil.virtual_memory().percent,
            "battery": bat.percent if bat else 100, 
            "people": current_people_count,
            "music": get_track_info()
        })

class VisionSystem:
    def __init__(self):
        self.face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        self.recognizer = cv2.face.LBPHFaceRecognizer_create()
        self.is_trained = False

    def train(self):
        faces, labels = [], []
        data_path = "images/"
        if not os.path.exists(data_path): return
        for dir_name in os.listdir(data_path):
            if not dir_name.isdigit(): continue
            label = int(dir_name)
            subject_path = os.path.join(data_path, dir_name)
            for img_name in os.listdir(subject_path):
                img = cv2.imread(os.path.join(subject_path, img_name), cv2.IMREAD_GRAYSCALE)
                if img is None: continue
                detected = self.face_cascade.detectMultiScale(img, 1.2, 5)
                for (x, y, w, h) in detected:
                    faces.append(img[y:y+h, x:x+w])
                    labels.append(label)
        if faces:
            self.recognizer.train(faces, np.array(labels))
            self.is_trained = True
            print(f"[VISION] Entraînée sur {len(faces)} visages.")

    def run(self):
        global current_people_count, last_seen_names
        cap = cv2.VideoCapture(0)
        while True:
            ret, frame = cap.read()
            if not ret: break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self.face_cascade.detectMultiScale(gray, 1.2, 5)
            current_people_count = len(faces)
            names = []
            for (x, y, w, h) in faces:
                name = "Inconnu"
                if self.is_trained:
                    label, conf = self.recognizer.predict(gray[y:y+h, x:x+w])
                    if conf < 80: name = subjects[label]
                names.append(name)
                cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
                cv2.putText(frame, name, (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            last_seen_names = names
            #cv2.imshow("Vision JARVIS", frame)
            #if cv2.waitKey(1) & 0xFF == ord('q'): break
        cap.release()
        cv2.destroyAllWindows()

# --- MOTEUR VOCAL ---
def voice_engine(bridge):
    if not os.path.exists(Config.VOSK_MODEL_PATH): return
    model = Model(Config.VOSK_MODEL_PATH)
    rec = KaldiRecognizer(model, 16000)
    mic = pyaudio.PyAudio()
    stream = mic.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=4000)
    
    print("J.A.R.V.I.S. en ligne.", bridge)
    while True:
        if mic_busy.is_set():
            time.sleep(0.1)
            continue
            
        data = stream.read(2000, exception_on_overflow=False)
        if rec.AcceptWaveform(data):
            res = json.loads(rec.Result())
            text = res.get("text", "")
            if len(text) > 2:
                bridge.send({"type": "user_msg", "content": text})
                response = brain.process(text, bridge)
                if response:
                    speak(response, bridge)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    bridge = JarvisBridge()
    ui = JarvisUI(bridge)
    check_spotify_silent()
    
    # Initialisation de la vision
    vision = VisionSystem()
    vision.train() # Entraînement au démarrage
    
    ui.show()
    
    # --- LANCEMENT DES THREADS ---
    # On lance la voix
    threading.Thread(target=voice_engine, args=(bridge,), daemon=True).start()
    
    # ON LANCE LA VISION (C'était ça l'oubli !)
    threading.Thread(target=vision.run, daemon=True).start()
    
    sys.exit(app.exec_())

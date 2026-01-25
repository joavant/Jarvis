import os, requests, chromadb, ollama, PyPDF2
from bs4 import BeautifulSoup
from docx import Document
from sentence_transformers import SentenceTransformer as st
from langchain_text_splitters import RecursiveCharacterTextSplitter as rctp
import ddgs
from concurrent.futures import ThreadPoolExecutor
import glob
from tqdm import tqdm
import sys
import time
import threading
import io
import contextlib
import re
from fpdf import FPDF

# 1. Initialisation
print("Initialisation de Jarvis Optimisé...")
timed = time.time()
# Modèle plus rapide et performant
model = st('all-MiniLM-L6-v2')
client = chromadb.PersistentClient(path=os.getenv("DB_PATH"))
collection = client.get_or_create_collection(name="#")
collection1 = client.get_or_create_collection(name="#")
chat_history = []
QUESTION_CACHE = {}
derniere_reponse_jarvis = ""
timea = time.time()
temps = timea - timed
minutes, secondes = divmod(temps,60)
print(f"Modeles chargé en {int(minutes)} minutes et {secondes:.2f}s")


def fusionner_tiroirs():
    timed = time.time()
    print("🔄 Fusion des tiroirs fragmentés...")
    cols = client.list_collections()
    
    # On regroupe les noms par version normalisée (MAJUSCULES)
    groupes = {}
    for col_info in cols:
        name = col_info.name if hasattr(col_info, 'name') else col_info
        norm = name.upper().strip()
        if norm not in groupes: groupes[norm] = []
        groupes[norm].append(name)

    for norm, anciens_noms in groupes.items():
        if len(anciens_noms) > 1:
            print(f"合并 {anciens_noms} -> [{norm}]")
            target_col = client.get_or_create_collection(name=norm)
            
            for ancien in anciens_noms:
                if ancien == norm: continue # Ne pas s'auto-copier
                old_col = client.get_collection(name=ancien)
                data = old_col.get(include=['metadatas', 'documents', 'embeddings'])
                
                if data['ids']:
                    # Transfert par batch de 4000
                    for i in range(0, len(data['ids']), 4000):
                        end = i + 4000
                        target_col.add(
                            ids=data['ids'][i:end],
                            documents=data['documents'][i:end],
                            metadatas=data['metadatas'][i:end],
                            embeddings=data['embeddings'][i:end]
                        )
                    client.delete_collection(name=ancien)
    timea = time.time()
    temps = timea - timed
    minutes, secondes = divmod(temps,60)
    print(f"Fusion terminée en {int(minutes)} minutes et {secondes:.2f}s")
    print("La mémoire est maintenant compacte.")

# Appelle cette fonction juste après l'initialisation du client
fusionner_tiroirs()


def extract_text(path):
    if not os.path.exists(path): return None
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".txt":
            with open(path, 'r', encoding='utf-8', errors='ignore') as f: return f.read()
        elif ext == ".pdf":
            reader = PyPDF2.PdfReader(path)
            return " ".join([page.extract_text() or "" for page in reader.pages])
        elif ext == ".docx":
            doc = Document(path)
            return "\n".join([p.text for p in doc.paragraphs])
    except Exception as e:
        print(f"Erreur lecture : {e}")
    return None

def extract_text_from_url(url):
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        titre = soup.title.string.strip() if soup.title else url
        for s in soup(["script", "style", "nav", "footer", "header"]): s.decompose()
        return soup.get_text(separator=' '), titre
    except: return None, None


from langchain_text_splitters import RecursiveCharacterTextSplitter, Language

def add_to_db(input_data, name, is_url=False, target_collection=None):
    # On nettoie le nom pour ne garder que 'rag2.py' au lieu du chemin complet
    nom_propre = os.path.basename(name) if not is_url else name

    # 1. Vérification d'existence
    for col_info in client.list_collections():
        c_name = col_info.name if hasattr(col_info, 'name') else col_info
        c = client.get_collection(name=c_name)
        if len(c.get(where={"source": nom_propre})['ids']) > 0:
            return 

    # 2. Extraction du texte
    contenu, _ = (extract_text_from_url(input_data)) if is_url else (extract_text(input_data), nom_propre)
    if not contenu or len(contenu) < 50: return

    # 3. Découpage intelligent (Hybrid Splitter)
    if nom_propre.lower().endswith('.py'):
        # Garde les fonctions et classes entières
        splitter = RecursiveCharacterTextSplitter.from_language(
            language=Language.PYTHON, chunk_size=2000, chunk_overlap=200
        )
    else:
        # Texte classique
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000, chunk_overlap=100, separators=["\n\n", "\n", ".", " ", ""]
        )

    chunks = splitter.split_text(contenu)
    embeddings = model.encode(chunks, show_progress_bar=False).tolist()
    nom_id_propre = nom_propre.replace('.', '_').replace('/', '_')
    ids = [f"{nom_id_propre}_{i}" for i in range(len(chunks))]
    metadatas = [{"source": nom_propre} for _ in range(len(chunks))]

    # 4. Insertion dans la collection cible ou auto-catégorie
    col = target_collection if target_collection else client.get_or_create_collection(name=determiner_categorie(nom_propre))
    col.add(documents=chunks, embeddings=embeddings, ids=ids, metadatas=metadatas)
    print(f"✅ Archivé proprement : {nom_propre} ➡️ [{col.name}]")


def determiner_categorie(url):
    import urllib.parse
    # On décode les %C3%A9 en 'é', etc.
    u = urllib.parse.unquote(url.lower())
    
    # Ordre strict : Science -> Histoire -> Philo -> Info
    if any(word in u for word in ["physique", "quantique", "relativit", "thermodynamique", "maxwell", "particule"]):
        return "Physique"
    if any(word in u for word in ["math", "calcul", "algèbr", "statistique", "nombre", "géométrie"]):
        return "Maths"
    if any(word in u for word in ["astro", "cosmologie", "trou-noir", "espace", "galaxie", "nasa"]):
        return "Astronomie"
    if any(word in u for word in ["chimie", "molécule", "organique", "atome"]):
        return "Chimie"
    if any(word in u for word in ["adn", "génétique", "biologie", "évolution", "cellule", "virus", "santé"]):
        return "Biologie"
    if any(word in u for word in ["histoire", "empire", "révolution", "siècle", "mondiale", "guerre", "antique", "moyen-âge"]):
        return "Histoire"
    if any(word in u for word in ["philo", "stoïcisme", "éthique", "socrate", "platon", "kant", "nietzsche", "utilitarisme"]):
        return "Philosophie"
    if any(word in u for word in ["éco", "finance", "bourse", "inflation", "pib", "marché", "macroéco"]):
        return "Economie"
    if any(word in u for word in ["sociologie", "droit", "géopolitique", "onu", "justice", "politique", "droit"]):
        return "Sociologie_Droit"
    if any(word in u for word in ["informatique", "code", "python", "algorithme", "intelligence-artificielle", "deep-learning", "linux", "réseau", "blockchain"]):
        return "Informatique_Codage"
    
    return "Divers"


# --- Boucle ---
while True:
    print("\n1: Fichier | 4:URL | q:Quitter ")
    choix = input("> ")
    
    if choix == '1':
        path = input("Chemin/URL : ").strip().replace("'", "")
        add_to_db(path, os.path.basename(path), is_url=path.startswith("http"))
        
    elif choix == '4':
        liste_path = input("Chemin du fichier .txt contenant les URLs : ").strip().replace("'", "")
        if os.path.exists(liste_path):
            with open(liste_path, 'r') as f:
                # On extrait proprement chaque URL
                urls = [line.strip() for line in f if line.strip().startswith("http")]
            
            print(f"🚀 Importation parallèle de {len(urls)} liens...")
            # On lance 4 téléchargements en même temps
            with ThreadPoolExecutor(max_workers=4) as executor:
                list(tqdm(executor.map(lambda u: add_to_db(u, u, is_url=True), urls), total=len(urls)))
            print("✨ Terminé !")
        else:
            print("❌ Fichier introuvable.")
    elif choix == 'q': 
        ollama.generate(model='llama3.2', prompt='', keep_alive=0)
        ollama.generate(model='qwen2.5:1.5b', prompt='', keep_alive=0)
        break

"""
Visualisateur
========================================
Extrait les embeddings de ChromaDB, calcule les similarites cosinus
entre tous les chunks, et produit un graphe JSON pour visualisation
interactive dans index.html

Usage:
    python build_mnemia_graph.py
    python build_mnemia_graph.py --threshold 0.6 --top-k 6
    python build_mnemia_graph.py --aggregate document
"""
import os
import json
import argparse
from collections import defaultdict

import numpy as np
import chromadb
from dotenv import load_dotenv

load_dotenv()

COLLECTIONS = [
    "#", "##",
]

# Palette JARVIS : chaque theme a une couleur signature stable
THEME_COLORS = {
    "#":              "#378ADD",  # bleu electrique
    "##":            "#7F77DD",  # violet stellaire
}


def cosine_sim_matrix(embeddings):
    """Matrice de similarite cosinus normalisee. Entree : (N, D)."""
    emb = np.asarray(embeddings, dtype=np.float32)
    norms = np.linalg.norm(emb, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1, norms)
    normed = emb / norms
    return normed @ normed.T


def extract_title(doc, fallback):
    """Extrait un titre lisible depuis le contenu du chunk."""
    if not doc:
        return fallback
    text = doc.strip().replace("\n", " ").replace("\r", " ")
    # On coupe a la fin du premier paragraphe ou apres 60 caracteres
    for sep in [". ", " - ", " : "]:
        if sep in text[:100]:
            head = text.split(sep, 1)[0]
            if 8 <= len(head) <= 80:
                return head
    return text[:60] + ("..." if len(text) > 60 else "")


def load_chunks(client, aggregate="chunk"):
    nodes = []
    embeddings = []
    counts = defaultdict(int)

    # Récupère dynamiquement toutes les collections si COLLECTIONS n'est pas adapté
    try:
        available_collections = [c.name for c in client.list_collections()]
    except Exception:
        available_collections = COLLECTIONS

    for col_name in available_collections:
        try:
            col = client.get_collection(name=col_name)
            data = col.get(include=["embeddings", "documents", "metadatas"])
        except Exception as e:
            print(f"    [skip] {col_name}: {e}")
            continue

        docs = data.get("documents")
        docs = docs if docs is not None else []
        
        embs = data.get("embeddings")
        embs = embs if embs is not None else []
        
        metas = data.get("metadatas")
        metas = metas if metas is not None else [{}] * len(docs)

        if not docs:
            continue

        if aggregate == "document":
            # Regroupe par source (champ metadata 'source' ou 'file')
            groups = defaultdict(list)
            for i, (doc, emb) in enumerate(zip(docs, embs)):
                meta = metas[i] if i < len(metas) else {}
                source = (meta or {}).get("source") or (meta or {}).get("file") or f"chunk_{i}"
                color = THEME_COLORS.get(col_name)
                if not color:
                  import hashlib
                    color = f"#{hashlib.md5(col_name.encode()).hexdigest()[:6]}"
                groups[source].append((doc, emb))

            for source, items in groups.items():
                avg_emb = np.mean([np.asarray(e) for _, e in items], axis=0)
                full_text = " ".join(d for d, _ in items)
                title = os.path.basename(str(source)).rsplit(".", 1)[0]
                nodes.append({
                    "id": f"{col_name}::{source}",
                    "theme": col_name,
                    "title": title or extract_title(full_text, col_name),
                    "content": full_text[:600],
                    "source": str(source),
                    "color": THEME_COLORS.get(col_name, "#888"),
                    "chunks": len(items),
                })
                embeddings.append(avg_emb)
                counts[col_name] += 1
        else:
            for i, (doc, emb) in enumerate(zip(docs, embs)):
                meta = metas[i] if i < len(metas) else {}
                source = (meta or {}).get("source") or (meta or {}).get("file") or "—"
                nodes.append({
                    "id": f"{col_name}::{i}",
                    "theme": col_name,
                    "title": extract_title(doc, f"{col_name} #{i}"),
                    "content": (doc or "")[:500],
                    "source": str(source),
                    "color": THEME_COLORS.get(col_name, "#888"),
                })
                embeddings.append(emb)
                counts[col_name] += 1

        print(f"    {col_name:<22} -> {counts[col_name]} noeuds")

    return nodes, embeddings, dict(counts)


def build_links(nodes, embeddings, threshold, top_k):
    """Construit les aretes par top-K voisins + seuil de similarite."""
    if len(nodes) < 2:
        return []

    print(f"\n[i] Calcul de la matrice de similarite ({len(nodes)} x {len(nodes)})...")
    sim = cosine_sim_matrix(embeddings)

    print(f"[i] Extraction des liens (top-{top_k}, seuil={threshold})...")
    seen = set()
    links = []

    for i in range(len(nodes)):
        row = sim[i].copy()
        row[i] = -1.0
        # Top-K indices (pas necessairement tries)
        if len(row) <= top_k:
            top_idx = np.arange(len(row))
        else:
            top_idx = np.argpartition(row, -top_k)[-top_k:]

        for j in top_idx:
            j = int(j)
            score = float(sim[i, j])
            if score < threshold:
                continue
            key = (min(i, j), max(i, j))
            if key in seen:
                continue
            seen.add(key)
            cross = nodes[i]["theme"] != nodes[j]["theme"]
            links.append({
                "source": nodes[i]["id"],
                "target": nodes[j]["id"],
                "weight": round(score, 3),
                "cross_theme": cross,
            })

    return links


def build_graph(db_path, threshold=0.55, top_k=6, aggregate="chunk", output="mnemia_brain.json"):
    print(f"[i] Connexion a ChromaDB : {db_path}")
    client = chromadb.PersistentClient(path=db_path)

    print(f"[i] Lecture des collections (mode: {aggregate})...")
    nodes, embeddings, counts = load_chunks(client, aggregate=aggregate)

    if not nodes:
        print("\n[!] Aucun chunk trouve. Verifie DB_PATH et les noms de collections.")
        return None

    links = build_links(nodes, embeddings, threshold, top_k)

    themes = [
        {"name": t, "count": c, "color": THEME_COLORS.get(t, "#888")}
        for t, c in sorted(counts.items(), key=lambda x: -x[1])
    ]
    cross_count = sum(1 for l in links if l["cross_theme"])

    graph = {
        "nodes": nodes,
        "links": links,
        "themes": themes,
        "stats": {
            "nodes": len(nodes),
            "links": len(links),
            "cross_theme_links": cross_count,
            "intra_theme_links": len(links) - cross_count,
            "threshold": threshold,
            "top_k": top_k,
            "aggregate": aggregate,
        },
    }

    with open(output, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False)

    pct = (100 * cross_count // max(1, len(links)))
    print(f"\n[OK] Graphe construit :")
    print(f"     Noeuds              : {graph['stats']['nodes']}")
    print(f"     Liens               : {graph['stats']['links']}")
    print(f"     Inter-thematiques   : {cross_count} ({pct}%)")
    print(f"     Intra-thematiques   : {len(links) - cross_count}")
    print(f"     Fichier             : {output}")
    return graph


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Construction du graphe Mnemia depuis ChromaDB")
    parser.add_argument("--threshold", type=float, default=0.55,
                        help="Seuil minimal de similarite cosinus (defaut: 0.55)")
    parser.add_argument("--top-k", type=int, default=6,
                        help="Nombre max de voisins par chunk (defaut: 6)")
    parser.add_argument("--aggregate", choices=["chunk", "document"], default="chunk",
                        help="Niveau de granularite : chunk (defaut) ou document")
    parser.add_argument("--db", type=str, default=os.getenv("DB_PATH"),
                        help="Chemin vers la base ChromaDB (sinon DB_PATH du .env)")
    parser.add_argument("--output", type=str, default="mnemia_brain.json",
                        help="Fichier JSON de sortie (defaut: mnemia_brain.json)")
    args = parser.parse_args()

    if not args.db:
        print("[!] Specifie --db ou definis DB_PATH dans .env")
        raise SystemExit(1)

    build_graph(args.db,
                threshold=args.threshold,
                top_k=args.top_k,
                aggregate=args.aggregate,
                output=args.output)

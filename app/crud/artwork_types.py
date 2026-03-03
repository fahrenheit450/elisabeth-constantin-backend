"""
CRUD operations for artwork_types collection.

Architecture propre:
- Pas de soft delete (suppression définitive uniquement)
- Pas de fusion avec les types des artworks
- Normalisation des noms pour comparaisons (via normalize_string)
- Source unique de vérité: la collection artwork_types
"""
from typing import List, Optional
from app.utils.string_utils import normalize_string
from bson.objectid import ObjectId
from app.database import get_database


def get_database_collection():
    """Récupère la collection artwork_types"""
    database = get_database()
    return database.artwork_types


def get_all_artwork_types() -> List[dict]:
    """
    Retourne tous les types d'œuvres depuis la collection artwork_types.
    
    Returns:
        Liste de documents {_id, name, display_name}
    """
    collection = get_database_collection()
    return list(collection.find({}))


def get_artwork_type_by_id(type_id: str) -> Optional[dict]:
    """
    Récupère un type d'œuvre par son _id.
    
    Args:
        type_id: L'ObjectId sous forme de string
        
    Returns:
        Le document du type ou None
    """
    try:
        oid = ObjectId(type_id)
    except Exception:
        return None
    
    collection = get_database_collection()
    return collection.find_one({"_id": oid})


def get_artwork_type_by_name(name: str, normalized: bool = True) -> Optional[dict]:
    """
    Récupère un type d'œuvre par son nom.
    
    Args:
        name: Le nom du type à chercher
        normalized: Si True, utilise la comparaison normalisée (insensible à la casse, accents, espaces)
        
    Returns:
        Le document du type ou None
    """
    if not name:
        return None
    
    collection = get_database_collection()
    
    if normalized:
        # Recherche normalisée (tolérante)
        normalized_search = normalize_string(name)
        for type_doc in collection.find({}):
            db_name = type_doc.get('name', '')
            if normalize_string(db_name) == normalized_search:
                return type_doc
        return None
    else:
        # Recherche stricte
        return collection.find_one({"name": name})


def create_artwork_type(name: str, display_name_fr: Optional[str] = None, display_name_en: Optional[str] = None) -> str:
    """
    Crée un nouveau type d'œuvre.
    
    Args:
        name: Le nom du type (unique, normalisé)
        display_name: Le nom d'affichage (optionnel, sinon capitalize du name)
        
    Returns:
        L'_id du document créé sous forme de string
        
    Raises:
        ValueError: Si le type existe déjà (comparaison normalisée)
    """
    if not name or not name.strip():
        raise ValueError("Le nom du type ne peut pas être vide")
    
    name = name.strip()
    
    # Vérifier l'unicité (comparaison normalisée)
    existing = get_artwork_type_by_name(name, normalized=True)
    if existing:
        raise ValueError(f"Le type '{name}' existe déjà (ou un équivalent normalisé)")
    
    # Préparer le document
    # Supporter display_name en FR/EN. Si l'admin passe une seule chaîne (compat),
    # elle sera utilisée pour FR.
    display_fr = None
    display_en = None
    if display_name_fr:
        display_fr = display_name_fr.strip()
    if display_name_en:
        display_en = display_name_en.strip()

    if not display_fr and display_name_en and not display_fr:
        display_fr = display_name_en

    if not display_fr:
        display_fr = name.capitalize()
    if not display_en:
        display_en = display_fr

    doc = {
        "name": name,
        "display_name": {"fr": display_fr, "en": display_en}
    }
    
    collection = get_database_collection()
    result = collection.insert_one(doc)
    return str(result.inserted_id)


def update_artwork_type(type_id: str, name: Optional[str] = None, display_name_fr: Optional[str] = None, display_name_en: Optional[str] = None) -> bool:
    """
    Met à jour un type d'œuvre.
    
    Args:
        type_id: L'_id du type à modifier
        name: Le nouveau nom (optionnel)
        display_name: Le nouveau display_name (optionnel)
        
    Returns:
        True si la mise à jour a réussi, False sinon
        
    Raises:
        ValueError: Si le nouveau nom existe déjà
    """
    try:
        oid = ObjectId(type_id)
    except Exception:
        return False
    
    collection = get_database_collection()
    
    # Vérifier que le type existe
    existing_type = collection.find_one({"_id": oid})
    if not existing_type:
        return False
    
    update_fields = {}
    
    # Si on change le nom, vérifier l'unicité
    if name is not None:
        name = name.strip()
        if not name:
            raise ValueError("Le nom du type ne peut pas être vide")
        
        # Vérifier que ce nom n'est pas déjà pris (sauf si c'est le même document)
        name_conflict = get_artwork_type_by_name(name, normalized=True)
        if name_conflict and str(name_conflict["_id"]) != type_id:
            raise ValueError(f"Le type '{name}' existe déjà")
        
        update_fields["name"] = name
    
    # Support bilingual display names
    if display_name_fr is not None or display_name_en is not None:
        # Keep existing or compute defaults
        existing_disp = existing_type.get('display_name')
        fr = None
        en = None
        if isinstance(existing_disp, dict):
            fr = existing_disp.get('fr')
            en = existing_disp.get('en')
        elif isinstance(existing_disp, str):
            fr = existing_disp
            en = existing_disp

        if display_name_fr is not None:
            fr = display_name_fr.strip() if display_name_fr else ""
        if display_name_en is not None:
            en = display_name_en.strip() if display_name_en else ""

        update_fields["display_name"] = {"fr": fr or name or existing_type.get('name', ''), "en": en or fr or name or existing_type.get('name', '')}
    
    if not update_fields:
        return False
    
    result = collection.update_one({"_id": oid}, {"$set": update_fields})
    return result.modified_count > 0


def delete_artwork_type(type_id: str) -> bool:
    """
    Supprime définitivement un type d'œuvre (hard delete).
    
    Args:
        type_id: L'_id du type à supprimer
        
    Returns:
        True si la suppression a réussi, False sinon
    """
    try:
        oid = ObjectId(type_id)
    except Exception:
        return False
    
    collection = get_database_collection()
    result = collection.delete_one({"_id": oid})
    return result.deleted_count > 0


def get_artwork_types_names() -> List[str]:
    """
    Retourne uniquement la liste des noms de types d'œuvres.
    Source unique: la collection artwork_types (pas de fusion avec artworks).
    
    Returns:
        Liste triée des noms de types
    """
    collection = get_database_collection()
    types_docs = list(collection.find({}, {"name": 1}))
    names = [doc["name"] for doc in types_docs if "name" in doc]
    return sorted(names)

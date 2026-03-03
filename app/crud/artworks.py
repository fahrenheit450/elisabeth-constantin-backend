from typing import List, Optional
from app.utils.string_utils import normalize_string
from bson.objectid import ObjectId
from app.database import artworks_collection

# Fields for which EN stored translations should be invalidated when FR source changes.
# NOTE: `type` is a canonical key managed via artwork_types and should not be translated.
TRANSLATABLE_FIELDS = {"title", "description", "status"}

def get_all_artworks() -> List[dict]:
    """
    Renvoie la liste de toutes les œuvres.
    """
    return list(artworks_collection.find())

def get_artwork_by_id(artwork_id: str) -> Optional[dict]:
    """
    Renvoie une seule œuvre correspondant à l'_id MongoDB.
    """
    try:
        oid = ObjectId(artwork_id)
    except Exception:
        return None
    return artworks_collection.find_one({"_id": oid})

def create_artwork(data: dict) -> str:
    """
    Insère une nouvelle œuvre.
    Retourne l'_id de la nouvelle entrée sous forme de chaîne.
    """
    data = dict(data)
    data.pop("_id", None)
    result = artworks_collection.insert_one(data)
    return str(result.inserted_id)

def update_artwork(artwork_id: str, update_data: dict) -> int:
    """
    Met à jour l'œuvre au _id donné avec les champs de update_data.
    Retourne le nombre de documents modifiés (0 ou 1).
    """
    try:
        oid = ObjectId(artwork_id)
    except Exception as e:
        return 0
    
    update_data = dict(update_data)
    update_data.pop("_id", None)
    
    # Vérifier si l'artwork existe
    existing = artworks_collection.find_one({"_id": oid})
    if not existing:
        return 0
    
    # Comparer les données pour voir s'il y a vraiment des changements
    has_changes = False
    changed_fields = []
    for key, new_value in update_data.items():
        existing_value = existing.get(key)
        if existing_value != new_value:
            has_changes = True
            changed_fields.append(key)
    
    # Si aucun changement, retourner 0 sans faire de requête DB
    if not has_changes:
        return 0
    
    update_payload = {"$set": update_data}

    translations = existing.get("translations", {})
    unset_fields = {}
    if translations.get("en"):
        for field in changed_fields:
            if field in TRANSLATABLE_FIELDS:
                unset_fields[f"translations.en.{field}"] = ""
    if unset_fields:
        update_payload["$unset"] = unset_fields

    result = artworks_collection.update_one(
        {"_id": oid},
        update_payload
    )
    return result.modified_count

def delete_artwork(artwork_id: str) -> int:
    """
    Supprime l'œuvre au _id donné.
    Retourne le nombre de documents supprimés (0 ou 1).
    """
    try:
        oid = ObjectId(artwork_id)
    except Exception:
        return 0
    result = artworks_collection.delete_one({"_id": oid})
    return result.deleted_count

def update_artwork_type(old_type: str, new_type: Optional[str]) -> int:
    """
    Met à jour le type d'œuvre dans toutes les œuvres ayant l'ancien type.
    Si new_type est None, met le champ à null (non défini).
    Retourne le nombre de documents modifiés.
    """
    
    try:
        # On normalise les comparaisons : parcourir les œuvres et matcher via normalize_string
        all_artworks = list(artworks_collection.find({}))
        to_update_ids = []
        for aw in all_artworks:
            aw_type = aw.get('type')
            if aw_type is None:
                continue
            if normalize_string(aw_type) == normalize_string(old_type):
                to_update_ids.append(aw.get('_id'))

        if not to_update_ids:
            return 0

        from bson import ObjectId
        object_ids = [ObjectId(i) if not isinstance(i, ObjectId) else i for i in to_update_ids]

        if new_type is None:
            result = artworks_collection.update_many(
                {"_id": {"$in": object_ids}},
                {"$set": {"type": None}}
            )
        else:
            result = artworks_collection.update_many(
                {"_id": {"$in": object_ids}},
                {"$set": {"type": new_type}}
            )

        return result.modified_count

    except Exception:
        return 0

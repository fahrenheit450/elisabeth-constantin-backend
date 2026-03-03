from fastapi import APIRouter, HTTPException, Request, BackgroundTasks, Query
from typing import List
from app.models.artwork import (
    Artwork,
    ArtworkInDB,
    UpdateTypeRequest,
    TranslateDescriptionRequest,
    UpdateDescriptionRequest,
)
from app.crud import artworks
from app.utils.string_utils import normalize_string
from fastapi import Depends
from api.auth_admin import require_admin_auth
from app.services.email.notifications import notify_new_artwork, notify_removed_artwork
from app.database import artworks_collection
from app.services.translation import _translate_with_deepl
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

SUPPORTED_LANGUAGES = {"fr", "en"}


def resolve_language(lang: str) -> str:
    if not lang:
        return "fr"
    normalized = lang.lower()
    return normalized if normalized in SUPPORTED_LANGUAGES else "fr"

def serialize_artwork(raw: dict, lang: str = "fr") -> dict:
    """
    Convertit le BSON ObjectId en str pour la sérialisation JSON.
    """
    # IMPORTANT: No automatic translation on read.
    # We only *use stored translations* (manual or via explicit admin translate endpoints).
    doc = dict(raw)
    translations = doc.get("translations", {}) or {}
    lang_translations = translations.get(lang, {}) or {}

    if lang != "fr":
        # Apply stored translations for supported fields
        if isinstance(lang_translations, dict):
            if lang_translations.get("description"):
                doc["description"] = lang_translations["description"]

    result = {
        **doc,
        "_id": str(doc["_id"]),
        "description": doc.get("description", "") or "",
        "other_images": doc.get("other_images", []),
        "status": doc.get("status", "Disponible"),
    }

    # Générer une vignette si l'image principale est hébergée sur Cloudinary
    try:
        main_image = doc.get('main_image', '') or ''
        if main_image and 'res.cloudinary.com' in main_image and '/upload/' in main_image:
            parts = main_image.split('/upload/')
            prefix, suffix = parts[0], parts[1]
            thumb_transform = 'upload/f_auto,q_auto,w_600/'
            thumbnail = prefix + '/' + thumb_transform + suffix
            result['thumbnail'] = thumbnail
        else:
            result['thumbnail'] = doc.get('thumbnail') if doc.get('thumbnail') else None
    except Exception:
        result['thumbnail'] = doc.get('thumbnail') if doc.get('thumbnail') else None
    return result

@router.get("/", response_model=List[ArtworkInDB])
def list_artworks(lang: str = Query("fr")):
    language = resolve_language(lang)
    raws = artworks.get_all_artworks()
    serialized = [serialize_artwork(a, language) for a in raws]
    return serialized

@router.get("/gallery-types", response_model=List[str])
def get_gallery_types():
    """
    DEPRECATED: Utiliser /api/artwork-types/ à la place.
    Retourne tous les types d'œuvres depuis la collection artwork_types.
    """
    from app.crud import artwork_types
    return artwork_types.get_artwork_types_names()

@router.get("/by-gallery/{gallery_type}", response_model=List[ArtworkInDB])
def get_artworks_by_gallery(gallery_type: str, lang: str = Query("fr")):
    """
    Retourne les œuvres d'un type de galerie spécifique
    """
    language = resolve_language(lang)
    artworks_data = artworks.get_all_artworks()
    filtered_artworks = []
    # Tolérance d'encodage : décoder + et %XX et gérer double-encodage éventuel
    from urllib.parse import unquote_plus
    decoded = gallery_type
    for _ in range(2):
        new = unquote_plus(decoded)
        if new == decoded:
            break
        decoded = new

    # Normaliser le type de galerie pour la comparaison (insensible à la casse, accents, espaces et caractères spéciaux)
    normalized_gallery_type = normalize_string(decoded)
    
    for artwork in artworks_data:
        # Normaliser le type de l'artwork de la même manière
        artwork_type = artwork.get('type', '') or ''
        normalized_artwork_type = normalize_string(artwork_type)
        
        # Filtrer seulement par type, pas par statut (afficher toutes les œuvres)
        if normalized_artwork_type == normalized_gallery_type:
            filtered_artworks.append(serialize_artwork(artwork, language))
    
    return filtered_artworks

@router.get("/gallery-types/all", response_model=List[str])
def get_all_gallery_types():
    """
    Retourne tous les types d'œuvres depuis la collection artwork_types.
    Source unique: pas de fallback vers les artworks.
    """
    from app.crud import artwork_types
    return artwork_types.get_artwork_types_names()

@router.get("/{artwork_id}", response_model=ArtworkInDB)
def get_artwork(artwork_id: str, lang: str = Query("fr")):
    language = resolve_language(lang)
    raw = artworks.get_artwork_by_id(artwork_id)
    if not raw:
        raise HTTPException(status_code=404, detail="Artwork not found")
    return serialize_artwork(raw, language)

@router.post("/", response_model=ArtworkInDB)
def create_artwork(
    artwork: Artwork,
    background_tasks: BackgroundTasks,
    _: bool = Depends(require_admin_auth),
    request: Request = None
):
    """
    Crée une nouvelle œuvre et notifie les abonnés à la newsletter.
    """
    created_id = artworks.create_artwork(artwork.dict())
    created_doc = artworks.get_artwork_by_id(created_id)
    if not created_doc:
        raise HTTPException(status_code=500, detail="Erreur lors de la récupération de l'œuvre créée")
    
    # Ajouter la tâche de notification en arrière-plan
    background_tasks.add_task(notify_new_artwork, created_id)
    logger.info(f"📧 Scheduled newsletter notification for new artwork: {created_id}")
    
    return serialize_artwork(created_doc)

# Déclarer les routes statiques avant '/{artwork_id}' pour éviter les collisions FastAPI

@router.put("/type/update")
def update_artwork_type(type_request: UpdateTypeRequest, _: bool = Depends(require_admin_auth), request: Request = None):
    """
    Met à jour un type d'œuvre dans toutes les œuvres
    """
    try:
        updated_count = artworks.update_artwork_type(type_request.oldType, type_request.newType)
        return {"success": True, "updated": updated_count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/translate-description")
def translate_description(
    request: TranslateDescriptionRequest,
    _: bool = Depends(require_admin_auth)
):
    """
    Traduit la description d'une œuvre en anglais via DeepL et la stocke en DB.
    Si une traduction existe déjà, elle est écrasée.
    """
    try:
        # Vérifier que l'artwork existe
        artwork = artworks.get_artwork_by_id(request.artwork_id)
        if not artwork:
            raise HTTPException(status_code=404, detail="Artwork not found")
        
        # Traduire avec DeepL
        translated_text = _translate_with_deepl(request.description_fr, "EN")
        if not translated_text:
            raise HTTPException(
                status_code=500,
                detail="DeepL translation failed (check DEEPL_API_KEY / DEEPL_API_URL)",
            )
        
        # Sauvegarder en DB dans translations.en.description
        oid = ObjectId(request.artwork_id)
        artworks_collection.update_one(
            {"_id": oid},
            {
                "$set": {
                    "translations.en.description": translated_text
                }
            }
        )
        
        logger.info(f"Translated description for artwork {request.artwork_id}")
        return {
            "success": True,
            "description_en": translated_text
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Translation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/update-description-en")
def update_description_en(
    request: UpdateDescriptionRequest,
    _: bool = Depends(require_admin_auth)
):
    """
    Met à jour manuellement la description anglaise d'une œuvre.
    """
    try:
        # Vérifier que l'artwork existe
        artwork = artworks.get_artwork_by_id(request.artwork_id)
        if not artwork:
            raise HTTPException(status_code=404, detail="Artwork not found")
        
        # Sauvegarder en DB
        oid = ObjectId(request.artwork_id)
        artworks_collection.update_one(
            {"_id": oid},
            {
                "$set": {
                    "translations.en.description": request.description_en
                }
            }
        )
        
        logger.info(f"Updated EN description for artwork {request.artwork_id}")
        return {
            "success": True,
            "description_en": request.description_en
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update description error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{artwork_id}", response_model=ArtworkInDB)
def update_artwork(artwork_id: str, artwork: Artwork, _: bool = Depends(require_admin_auth), request: Request = None):
    # Vérifier d'abord que l'artwork existe
    existing_doc = artworks.get_artwork_by_id(artwork_id)
    if not existing_doc:
        raise HTTPException(status_code=404, detail="Artwork not found")
    
    modified_count = artworks.update_artwork(artwork_id, artwork.dict())
    
    # Si aucune modification n'a été faite, retourner l'artwork existant
    # (cela peut arriver si les données sont identiques)
    if modified_count == 0:
        return serialize_artwork(existing_doc)
    
    # Sinon, récupérer l'artwork mis à jour
    updated_doc = artworks.get_artwork_by_id(artwork_id)
    if not updated_doc:
        raise HTTPException(status_code=404, detail="Artwork not found after update")
    return serialize_artwork(updated_doc)

@router.delete("/{artwork_id}")
def delete_artwork(
    artwork_id: str,
    background_tasks: BackgroundTasks,
    _: bool = Depends(require_admin_auth),
    request: Request = None
):
    """
    Supprime une œuvre et notifie les abonnés à la newsletter.
    """
    # Récupérer l'artwork AVANT de le supprimer (pour l'email)
    artwork_data = artworks.get_artwork_by_id(artwork_id)
    if not artwork_data:
        raise HTTPException(status_code=404, detail="Artwork not found")
    
    # Supprimer l'artwork
    deleted = artworks.delete_artwork(artwork_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Artwork not found")
    
    # Ajouter la tâche de notification en arrière-plan
    # Passer les données de l'artwork (car il est supprimé)
    background_tasks.add_task(notify_removed_artwork, serialize_artwork(artwork_data))
    logger.info(f"📧 Scheduled newsletter notification for removed artwork: {artwork_id}")
    
    return {"message": "Artwork deleted successfully"}

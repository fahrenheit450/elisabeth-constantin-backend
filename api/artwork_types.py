"""
API routes pour la gestion des types d'œuvres.

Architecture propre:
- GET / : liste tous les types
- POST / : crée un type (admin only)
- PUT /{type_name} : renomme un type et met à jour tous les artworks (admin only)
- DELETE /{type_name} : supprime un type et met les artworks.type à null (admin only)
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import List
from pydantic import BaseModel

from api.auth_admin import require_admin_auth
from app.crud import artworks as artworks_crud
from app.crud import artwork_types as types_crud
from app.services.translation import _translate_with_deepl

router = APIRouter()


class CreateTypeRequest(BaseModel):
    name: str
    display_name_fr: str | None = None
    display_name_en: str | None = None


class UpdateTypeRequest(BaseModel):
    newType: str
    display_name_fr: str | None = None
    display_name_en: str | None = None


@router.get("/", response_model=List[str])
def get_artwork_types():
    """
    Retourne tous les types d'œuvres depuis la collection artwork_types.
    Source unique: pas de fusion avec les types des artworks.
    
    Returns:
        Liste triée des noms de types
    """
    return types_crud.get_artwork_types_names()


@router.post("/")
def create_artwork_type(request: CreateTypeRequest, _: bool = Depends(require_admin_auth)):
    """
    Crée un nouveau type d'œuvre.
    
    Args:
        request: {name, display_name (optional)}
        
    Returns:
        {message, type_id, type_name}
        
    Raises:
        400: Si le nom est vide ou si le type existe déjà
    """
    type_name = request.name.strip() if request.name else ""
    
    if not type_name:
        raise HTTPException(status_code=400, detail="Le nom du type ne peut pas être vide")
    
    try:
        type_id = types_crud.create_artwork_type(
            name=type_name,
            display_name_fr=request.display_name_fr,
            display_name_en=request.display_name_en
        )
        return {
            "message": f"Type '{type_name}' créé avec succès",
            "type_id": type_id,
            "type_name": type_name
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{type_name}/translate-en")
def translate_type_display_en(type_name: str, _: bool = Depends(require_admin_auth)):
    """Auto-translate display_name.fr -> display_name.en for an existing type."""
    from urllib.parse import unquote_plus
    decoded_name = type_name
    for _ in range(2):
        new = unquote_plus(decoded_name)
        if new == decoded_name:
            break
        decoded_name = new

    existing = types_crud.get_artwork_type_by_name(decoded_name, normalized=True)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Le type '{decoded_name}' n'existe pas")

    display = existing.get('display_name')
    source_fr = None
    if isinstance(display, dict):
        source_fr = display.get('fr')
    elif isinstance(display, str):
        source_fr = display

    if not source_fr:
        source_fr = existing.get('name', decoded_name)

    translated = _translate_with_deepl(source_fr, "EN")
    if not translated:
        raise HTTPException(status_code=500, detail="Translation failed")

    type_id = str(existing['_id'])
    ok = types_crud.update_artwork_type(type_id=type_id, display_name_en=translated)
    if not ok:
        raise HTTPException(status_code=500, detail="Erreur lors de la mise à jour du type")

    return {"success": True, "type": existing.get('name', decoded_name), "display_name_en": translated}


@router.delete("/{type_name}")
def delete_artwork_type(type_name: str, _: bool = Depends(require_admin_auth)):
    """
    Supprime un type d'œuvre et met à null le champ type de tous les artworks concernés.
    
    Args:
        type_name: Le nom du type à supprimer
        
    Returns:
        {message, artworks_updated}
        
    Raises:
        404: Si le type n'existe pas
    """
    # Tolérance d'encodage des paramètres de path (plus et %xx, double-encodage)
    from urllib.parse import unquote_plus
    decoded_name = type_name
    for _ in range(2):
        new = unquote_plus(decoded_name)
        if new == decoded_name:
            break
        decoded_name = new

    # Vérifier que le type existe
    existing = types_crud.get_artwork_type_by_name(decoded_name, normalized=True)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Le type '{decoded_name}' n'existe pas")

    type_id = str(existing["_id"])

    # Mettre à null le type de tous les artworks concernés (via normalized matching)
    modified_count = artworks_crud.update_artwork_type(decoded_name, None)
    
    # Supprimer le type de la collection artwork_types
    success = types_crud.delete_artwork_type(type_id)
    
    if not success:
        raise HTTPException(status_code=500, detail="Erreur lors de la suppression du type")
    
    return {
        "message": f"Type '{type_name}' supprimé avec succès",
        "artworks_updated": modified_count
    }


@router.put("/{type_name}")
def update_artwork_type_endpoint(
    type_name: str, 
    request: UpdateTypeRequest, 
    _: bool = Depends(require_admin_auth)
):
    """
    Renomme un type d'œuvre et applique le changement à tous les artworks concernés.
    
    Args:
        type_name: Le nom actuel du type
        request: {newType, display_name (optional)}
        
    Returns:
        {message, artworks_updated}
        
    Raises:
        400: Si le nouveau nom est vide, identique à l'ancien, ou existe déjà
        404: Si le type actuel n'existe pas
    """
    new_type = request.newType.strip() if request.newType else ""
    
    if not new_type:
        raise HTTPException(status_code=400, detail="Le nouveau nom de type ne peut pas être vide")
    
    # Tolérance d'encodage du paramètre path
    from urllib.parse import unquote_plus
    decoded_name = type_name
    for _ in range(2):
        new = unquote_plus(decoded_name)
        if new == decoded_name:
            break
        decoded_name = new

    # Vérifier que l'ancien type existe
    existing_old = types_crud.get_artwork_type_by_name(decoded_name, normalized=True)
    if not existing_old:
        raise HTTPException(status_code=404, detail=f"Le type '{decoded_name}' n'existe pas")

    # Vérifier que le nouveau nom est différent (comparaison normalisée)
    from app.utils.string_utils import normalize_string
    if normalize_string(decoded_name) == normalize_string(new_type):
        raise HTTPException(status_code=400, detail="Le nouveau type doit être différent de l'ancien")
    
    # Vérifier que le nouveau nom n'est pas déjà pris
    existing_new = types_crud.get_artwork_type_by_name(new_type, normalized=True)
    if existing_new:
        raise HTTPException(
            status_code=400,
            detail=f"Le type '{new_type}' existe déjà. Utilisez un nom différent."
        )
    
    type_id = str(existing_old["_id"])
    
    try:
        # Mettre à jour le nom dans la collection artwork_types
        success = types_crud.update_artwork_type(
            type_id=type_id,
            name=new_type,
            display_name_fr=request.display_name_fr,
            display_name_en=request.display_name_en
        )

        if not success:
            raise HTTPException(status_code=500, detail="Erreur lors de la mise à jour du type")

        # Mettre à jour tous les artworks ayant ce type
        modified_count = artworks_crud.update_artwork_type(decoded_name, new_type)

        return {
            "message": f"Type '{decoded_name}' modifié en '{new_type}' avec succès",
            "artworks_updated": modified_count
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

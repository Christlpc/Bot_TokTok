# chatbot/conversation_flow_coursier.py
from __future__ import annotations
import os, re, logging, requests
from typing import Dict, Any, Optional
from .auth_core import get_session, build_response, normalize
from .conversation_flow import ai_fallback  # réutilise la fonction IA
from .analytics import analytics

logger = logging.getLogger(__name__)

API_BASE = os.getenv("TOKTOK_BASE_URL", "https://toktok-bsfz.onrender.com")
TIMEOUT = int(os.getenv("TOKTOK_TIMEOUT", "15"))

MAIN_MENU_BTNS = ["Nouvelle demande", "Suivre ma demande", "Marketplace"]

# --- Helpers UI ---
def _fmt_fcfa(n: int | str | None) -> str:
    try:
        i = int(str(n or 0))
        # séparateur fin (espace insécable)
        return f"{i:,}".replace(",", " ")
    except Exception:
        return str(n or 0)

def _format_mission_status_timeline(statut: str) -> str:
    """
    Affiche le statut de la mission avec une timeline visuelle
    
    Args:
        statut: Statut de la mission (pending, accepted, in_transit, delivered, etc.)
    
    Returns:
        String formaté avec timeline et émojis
    """
    statut_lower = (statut or "").lower()
    
    # Timeline visuelle selon le statut
    if statut_lower in {"pending", "en_attente", "new"}:
        return (
            "*📊 TIMELINE*\n"
            "🔵 Demande créée\n"
            "⚪ Livreur assigné\n"
            "⚪ Récupération\n"
            "⚪ En transit\n"
            "⚪ Livré\n\n"
            "⏱️ *Statut actuel :* _En attente d'un livreur_"
        )
    
    elif statut_lower in {"accepted", "assigned", "confirme"}:
        return (
            "*📊 TIMELINE*\n"
            "✅ Demande créée\n"
            "🔵 Livreur assigné\n"
            "⚪ Récupération\n"
            "⚪ En transit\n"
            "⚪ Livré\n\n"
            "⏱️ *Statut actuel :* _En route vers le départ_"
        )
    
    elif statut_lower in {"pickup_arrived", "arrive_pickup", "au_depart"}:
        return (
            "*📊 TIMELINE*\n"
            "✅ Demande créée\n"
            "✅ Livreur assigné\n"
            "🔵 Récupération\n"
            "⚪ En transit\n"
            "⚪ Livré\n\n"
            "⏱️ *Statut actuel :* _Récupération en cours_"
        )
    
    elif statut_lower in {"in_transit", "en_route", "picked_up"}:
        return (
            "*📊 TIMELINE*\n"
            "✅ Demande créée\n"
            "✅ Livreur assigné\n"
            "✅ Récupération\n"
            "🔵 En transit\n"
            "⚪ Livré\n\n"
            "⏱️ *Statut actuel :* _En route vers la destination_"
        )
    
    elif statut_lower in {"delivered", "livree", "completed", "termine"}:
        return (
            "*📊 TIMELINE*\n"
            "✅ Demande créée\n"
            "✅ Livreur assigné\n"
            "✅ Récupération\n"
            "✅ En transit\n"
            "✅ Livré\n\n"
            "🎉 *Statut actuel :* _Livraison terminée !_"
        )
    
    elif statut_lower in {"cancelled", "annule", "canceled"}:
        return (
            "*📊 TIMELINE*\n"
            "✅ Demande créée\n"
            "❌ Mission annulée\n\n"
            "⚠️ *Statut actuel :* _Annulée_"
        )
    
    else:
        # Statut inconnu
        return f"*📊 Statut :* _{statut}_"

def _headers(session: Dict[str, Any]) -> Dict[str, str]:
    tok = (session.get("auth") or {}).get("access")
    return {"Authorization": f"Bearer {tok}"} if tok else {}

def api_request(session: Dict[str, Any], method: str, path: str, **kwargs):
    headers = {**_headers(session), **kwargs.pop("headers", {})}
    url = f"{API_BASE}{path}"
    r = requests.request(method, url, headers=headers, timeout=TIMEOUT, **kwargs)
    logger.debug(f"[API-C] {method} {path} -> {r.status_code}")
    return r

# --- Suivi & Historique ---
def handle_follow(session: Dict[str, Any]) -> Dict[str, Any]:
    """Affiche la liste des dernières demandes et demande la référence à suivre."""
    session["step"] = "FOLLOW_WAIT"
    try:
        if not (session.get("auth") or {}).get("access"):
            return build_response("⚠️ Vous devez être connecté pour suivre vos demandes.", MAIN_MENU_BTNS)

        r = api_request(session, "GET", "/api/v1/coursier/missions/")
        if not r.ok:
            logger.error(f"[FOLLOW_LIST] API error: {r.status_code}")
            return build_response("❌ Impossible de charger vos demandes.", MAIN_MENU_BTNS)
        
        data = r.json() or {}
        missions = data.get("results", [])[:3]

        if not missions:
            return build_response(
                "*🗂️ HISTORIQUE*\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "Vous n'avez aucune demande en cours.\n\n"
                "💡 _Créez votre première demande dès maintenant !_",
                MAIN_MENU_BTNS
            )

        lignes = []
        for m in missions:
            ref_long = m.get("numero_mission", "-")
            suffixe = ref_long.split("-")[-1] if ref_long else "?"
            ref_courte = f"#{suffixe}"
            statut = m.get("statut", "-")
            dest = m.get("adresse_livraison", "-")
            lignes.append(f"{ref_courte} → {dest} ({statut})")

        txt = (
            "*🔍 SUIVI DE VOS DEMANDES*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "*Vos dernières demandes :*\n" + "\n".join(lignes) + "\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "💡 *Entrez la référence pour voir les détails*\n\n"
            "_Exemple :_ `COUR-20250919-003` ou `#003`"
        )
        return build_response(txt, ["🔙 Retour"])

    except Exception as e:
        logger.exception(f"[FOLLOW_LIST] error: {e}")
        return build_response("❌ Impossible de charger vos demandes.", MAIN_MENU_BTNS)


def follow_lookup(session: Dict[str, Any], text: str) -> Dict[str, Any]:
    """Recherche et affiche les détails d'une demande spécifique."""
    try:
        if not (session.get("auth") or {}).get("access"):
            return build_response("⚠️ Vous devez être connecté pour suivre vos demandes.", MAIN_MENU_BTNS)

        r = api_request(session, "GET", "/api/v1/coursier/missions/")
        if not r.ok:
            logger.error(f"[FOLLOW_LOOKUP] API error: {r.status_code}")
            return build_response("❌ Impossible de charger vos demandes.", MAIN_MENU_BTNS)
        
        data = r.json() or {}
        all_missions = data.get("results", [])

        if not all_missions:
            return build_response("❌ Vous n'avez aucune demande enregistrée.", MAIN_MENU_BTNS)

        ref = text.strip()
        mission = None

        # Recherche exacte par numero_mission
        mission = next((m for m in all_missions if m.get("numero_mission") == ref), None)
        
        # Recherche par suffixe (#003)
        if not mission and ref.lstrip("#").isdigit():
            suffixe = ref.lstrip("#")
            mission = next(
                (m for m in all_missions if m.get("numero_mission", "").endswith(f"-{suffixe}")),
                None
            )
        
        # Recherche par alias M-ID
        if not mission and ref.upper().startswith("M-") and ref[2:].isdigit():
            alias = ref[2:]
            mission = next(
                (m for m in all_missions if str(m.get("id")) == alias),
                None
            )

        if not mission:
            return build_response(
                "🔍 *Référence introuvable*\n\n"
                f"Aucune demande ne correspond à `{ref}`.\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "💡 *Vérifiez la référence*\n"
                "_Format :_ `COUR-20250919-003` ou `#003`\n\n"
                "Ou tapez *Menu* pour revenir.",
                ["Menu"]
            )

        # Récupérer les détails complets
        mission_id = mission.get("id")
        r2 = api_request(session, "GET", f"/api/v1/coursier/missions/{mission_id}/")
        if not r2.ok:
            logger.error(f"[FOLLOW_LOOKUP] details API error: {r2.status_code}")
            return build_response("❌ Erreur lors du chargement des détails.", MAIN_MENU_BTNS)
        
        d = r2.json()

        depart_aff = "Position partagée" if d.get("coordonnees_recuperation") else d.get("adresse_recuperation", "-")

        # Formater le statut avec icône et timeline
        statut = d.get('statut', '-')
        statut_display = _format_mission_status_timeline(statut)
        
        recap = (
            f"*📦 DEMANDE {d.get('numero_mission', '-')}*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{statut_display}\n\n"
            "*📍 ITINÉRAIRE*\n"
            f"🚏 Départ : _{depart_aff}_\n"
            f"🎯 Arrivée : _{d.get('adresse_livraison', '-')}_\n\n"
            "*👤 DESTINATAIRE*\n"
            f"• Nom : *{d.get('nom_client_final', '-')}*\n"
            f"• Tél : `{d.get('telephone_client_final', '-')}`\n\n"
            "*💰 VALEUR*\n"
            f"{_fmt_fcfa(d.get('valeur_produit', 0))} FCFA\n"
        )
        
        # Ajouter info livreur si disponible
        if d.get('livreur_nom'):
            recap += f"\n*🚴 LIVREUR*\n• {d['livreur_nom']}"
            if d.get('livreur_telephone'):
                recap += f"\n• Tél : `{d['livreur_telephone']}`"
            recap += "\n"

        if d.get("statut") in {"assigned", "en_route", "completed"}:
            if d.get("livreur_nom"):
                recap += f"\n🚴 Livreur : {d['livreur_nom']} ({d.get('livreur_telephone', '-')})\n"
            if d.get("distance_estimee"):
                recap += f"📏 Distance : {d['distance_estimee']}\n"

        session["step"] = "MENU"
        return build_response(recap.strip(), MAIN_MENU_BTNS)

    except Exception as e:
        logger.exception(f"[FOLLOW_LOOKUP] error: {e}")
        return build_response("❌ Erreur lors du suivi de la demande.", MAIN_MENU_BTNS)


# --- Création mission ---
def courier_create(session: Dict[str, Any]) -> Dict[str, Any]:
    d = session.setdefault("new_request", {})
    try:
        # Vérification minimum avant envoi
        if not d.get("destination") and not d.get("coordonnees_livraison"):
            session["step"] = "COURIER_DEST"
            return build_response("📍 Indiquez l’adresse de destination ou partagez la position du point de livraison.")

        payload = {
            "entreprise_demandeur": (session.get("user") or {}).get("display_name") or "Client TokTok",
            "contact_entreprise": session.get("phone"),
            "adresse_recuperation": d.get("depart") or "",
            "coordonnees_recuperation": d.get("coordonnees_gps", ""),
            "adresse_livraison": d.get("destination") or "Position partagée",
            "coordonnees_livraison": d.get("coordonnees_livraison", ""),
            "nom_client_final": d.get("destinataire_nom") or "",
            "telephone_client_final": d.get("destinataire_tel") or "",
            "description_produit": d.get("description") or "",
            "valeur_produit": str(d.get("value_fcfa") or 0),
            "type_paiement": d.get("payment_method", "entreprise_paie"),
        }
        r = api_request(session, "POST", "/api/v1/coursier/missions/", json=payload)
        r.raise_for_status()
        mission = r.json()
        logger.info(f"[COURIER] create_mission response: {mission}")
        
        session["step"] = "MENU"

        # Récupérer la référence avec plusieurs fallbacks
        mission_id = mission.get("id") or mission.get("mission_id") or "?"
        ref = mission.get("numero_mission") or f"M-{mission_id}"
        
        logger.info(f"[COURIER] mission reference: {ref}")
        
        # Track conversion
        try:
            value = float(d.get("value_fcfa", 0))
            analytics.track_conversion(
                session.get("phone"),
                "mission_created",
                value,
                {"mission_ref": ref, "mission_id": mission_id}
            )
        except Exception as e:
            logger.warning(f"[COURIER] Could not track conversion: {e}")
        
        msg = (
            "🎉 *MISSION CRÉÉE AVEC SUCCÈS*\n\n"
            f"*Référence :* `{ref}`\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "*📍 ITINÉRAIRE*\n"
            f"🚏 Départ : _{d.get('depart', '—')}_\n"
            f"🎯 Arrivée : _{d.get('destination', '—')}_\n\n"
            "*⏱️ STATUT ACTUEL*\n"
            "🔍 _Recherche d'un livreur disponible..._\n\n"
            "💡 *Vous recevrez une notification dès qu'un livreur acceptera votre demande.*"
        )
        # On nettoie le brouillon pour la prochaine demande
        session.pop("new_request", None)
        return build_response(msg, MAIN_MENU_BTNS)

    except Exception as e:
        logger.exception(f"[COURIER] create_mission exception: {e}")
        return build_response(
            "⚠️ *Erreur temporaire*\n\n"
            "Nous n'avons pas pu créer votre demande.\n\n"
            "🔄 _Veuillez réessayer dans quelques instants._\n\n"
            "📞 _Si le problème persiste, contactez notre support._",
            MAIN_MENU_BTNS
        )

# --- Flow principal ---
def flow_coursier_handle(session: Dict[str, Any], text: str, lat: Optional[float] = None, lng: Optional[float] = None) -> Dict[str, Any]:
    step = session.get("step")
    t = normalize(text).lower() if text else ""

    # Menu principal - Options disponibles
    if t in {"suivre ma demande", "suivre", "2"} or "suivre" in t:
        return handle_follow(session)
    
    if t in {"menu", "accueil"}:
        session["step"] = "MENU"
        session.pop("new_request", None)
        return build_response("🏠 Menu principal", MAIN_MENU_BTNS)

    # Gestion bouton retour contextuel - étape par étape
    if t in {"retour", "back", "🔙 retour"}:
        current_step = session.get("step", "")
        
        # Retour depuis FOLLOW_WAIT vers menu
        if current_step == "FOLLOW_WAIT":
            session["step"] = "MENU"
            return build_response("🏠 Menu principal", MAIN_MENU_BTNS)
        
        # Récupérer la position du client pour navigation adaptée
        d = session.get("new_request", {})
        client_position = d.get("client_position")
        
        # Navigation contexuelle selon l'étape
        if current_step == "COURIER_POSITION_TYPE":
            session["step"] = "MENU"
            session.pop("new_request", None)
            return build_response("🏠 Menu principal", MAIN_MENU_BTNS)
        
        elif current_step == "COURIER_DEPART_GPS":
            session["step"] = "COURIER_POSITION_TYPE"
            return build_response(
                "📍 *Où vous trouvez-vous actuellement ?*\n\nCela nous permettra de mieux organiser la livraison.",
                ["Au point de départ", "Au point d'arrivée", "🔙 Retour"]
            )
        
        elif current_step == "COURIER_DEST_GPS":
            session["step"] = "COURIER_POSITION_TYPE"
            return build_response(
                "📍 *Où vous trouvez-vous actuellement ?*\n\nCela nous permettra de mieux organiser la livraison.",
                ["Au point de départ", "Au point d'arrivée", "🔙 Retour"]
            )
        
        elif current_step == "COURIER_DEST_TEXT":
            session["step"] = "COURIER_DEPART_GPS"
            resp = build_response(
                "📍 Parfait ! *Partagez votre position actuelle*\n(c'est là où le colis sera récupéré)",
                ["🔙 Retour"]
            )
            resp["ask_location"] = True
            return resp
        
        elif current_step == "COURIER_DEPART_TEXT":
            session["step"] = "COURIER_DEST_GPS"
            resp = build_response(
                "📍 Parfait ! *Partagez votre position actuelle*\n(c'est là où le colis sera livré)",
                ["🔙 Retour"]
            )
            resp["ask_location"] = True
            return resp
        
        elif current_step == "DEST_NOM":
            session["step"] = "COURIER_DEST_TEXT"
            return build_response(
                "📍 Maintenant, quelle est l'*adresse de destination* ?\nEx. `25 Rue Malanda, Poto-Poto`",
                ["🔙 Retour"]
            )
        
        elif current_step == "EXPEDITEUR_NOM":
            session["step"] = "COURIER_DEPART_TEXT"
            return build_response(
                "📍 Maintenant, quelle est l'*adresse de départ* ?\n(d'où le colis doit être récupéré)\nEx. `10 Avenue de la Paix, BZV`",
                ["🔙 Retour"]
            )
        
        elif current_step == "DEST_TEL":
            session["step"] = "DEST_NOM"
            return build_response(
                "👤 Quel est le *nom du destinataire* ?\n(la personne qui recevra le colis)\nEx. `Jean Malonga`",
                ["🔙 Retour"]
            )
        
        elif current_step == "EXPEDITEUR_TEL":
            session["step"] = "EXPEDITEUR_NOM"
            return build_response(
                "👤 Quel est le *nom de l'expéditeur* ?\n(la personne qui détient le colis)\nEx. `Marie Okemba`",
                ["🔙 Retour"]
            )
        
        elif current_step == "COURIER_VALUE":
            # Retourner vers l'étape précédente selon la position du client
            if client_position == "arrivee":
                session["step"] = "EXPEDITEUR_TEL"
            else:
                session["step"] = "DEST_TEL"
            return build_response("📞 Son *numéro de téléphone* ? (ex. `06 555 00 00`)", ["🔙 Retour"])
        
        elif current_step == "COURIER_DESC":
            session["step"] = "COURIER_VALUE"
            return build_response("💰 Quelle est la *valeur estimée* du colis (en FCFA) ?\nEx. `15000`", ["🔙 Retour"])
        
        elif current_step == "COURIER_CONFIRM":
            session["step"] = "COURIER_DESC"
            return build_response("📦 Décrivez brièvement le colis.  \nEx. `Dossier A4 scellé, Paquet 2 kg`.", ["🔙 Retour"])
        elif current_step == "COURIER_EDIT":
            # Retour depuis modification → confirmation
            session["step"] = "COURIER_CONFIRM"
            d = session.get("new_request", {})
            dest_aff = "Position partagée" if d.get("coordonnees_livraison") else d.get("destination")
            recap = (
                "📝 *Récapitulatif*\n"
                f"• Départ : {d.get('depart')}\n"
                f"• Destination : {dest_aff}\n"
                f"• Destinataire : {d.get('destinataire_nom')} ({d.get('destinataire_tel')})\n"
                f"• Valeur : {_fmt_fcfa(d.get('value_fcfa'))} FCFA\n"
                f"• Description : {d.get('description')}\n\n"
                "Tout est bon ?"
            )
            return build_response(recap, ["Confirmer", "Modifier", "🔙 Retour"])
        else:
            # Défaut : retour au menu
            session["step"] = "MENU"
            session.pop("new_request", None)
            return build_response("🏠 Menu principal", MAIN_MENU_BTNS)

    # Raccourcis menu
    if t in {"menu", "accueil", "0"}:
        session["step"] = "MENU"
        session.pop("new_request", None)
        return build_response("🏠 Menu principal — que souhaitez-vous faire ?", MAIN_MENU_BTNS)

    # Début du flow - Demander où se trouve le client
    if step in {None, "MENU", "AUTHENTICATED"} and (t in {"nouvelle demande", "1"} or "nouvelle demande" in t):
        session.pop("new_request", None)  # Nettoyer au départ
        session["step"] = "COURIER_POSITION_TYPE"
        return build_response(
            "*📦 NOUVELLE DEMANDE DE LIVRAISON*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "[░░░░░░░░░░] 0% · _Initialisation_\n\n"
            "📍 *Où vous trouvez-vous actuellement ?*\n\n"
            "_Cela nous permettra de mieux organiser la livraison._",
            ["Au point de départ", "Au point d'arrivée", "🔙 Retour"]
        )
    
    # Gérer la réponse sur la position du client
    if step == "COURIER_POSITION_TYPE":
        if t in {"au point de depart", "depart", "point de depart", "1"} or "depart" in t:
            session.setdefault("new_request", {})["client_position"] = "depart"
            session["step"] = "COURIER_DEPART_GPS"
            resp = build_response(
                "[▓▓░░░░░░░░] 20% · _Position de départ_\n\n"
                "📍 *Partagez votre position actuelle*\n\n"
                "_C'est là où le colis sera récupéré_\n\n"
                "💡 _Appuyez sur le 📎 puis \"Position\"_",
                ["🔙 Retour"]
            )
            resp["ask_location"] = True
            return resp
        elif t in {"au point d'arrivee", "arrivee", "point d'arrivee", "destination", "2"} or "arrivee" in t or "arrivée" in t:
            session.setdefault("new_request", {})["client_position"] = "arrivee"
            session["step"] = "COURIER_DEST_GPS"
            resp = build_response(
                "[▓▓░░░░░░░░] 20% · _Position d'arrivée_\n\n"
                "📍 *Partagez votre position actuelle*\n\n"
                "_C'est là où le colis sera livré_\n\n"
                "💡 _Appuyez sur le 📎 puis \"Position\"_",
                ["🔙 Retour"]
            )
            resp["ask_location"] = True
            return resp
        else:
            return build_response(
                "⚠️ Veuillez choisir une option :",
                ["Au point de départ", "Au point d'arrivée", "🔙 Retour"]
            )

    # Localisation partagée (reçue depuis WhatsApp)
    if (lat is not None and lng is not None) or (text and text.strip().upper() == "LOCATION_SHARED"):
        # Si on a pas lat/lng mais text="LOCATION_SHARED", récupérer depuis session
        if lat is None or lng is None:
            last_loc = session.get("last_location", {})
            lat = last_loc.get("latitude")
            lng = last_loc.get("longitude")
        
        nr = session.setdefault("new_request", {})
        client_position = nr.get("client_position")
        
        # Cas 1: Client est au point de départ (partage sa position = départ)
        if step == "COURIER_DEPART_GPS" and lat and lng:
            nr["depart"] = "Position actuelle"
            nr["coordonnees_gps"] = f"{lat},{lng}"
            nr["latitude_depart"] = lat
            nr["longitude_depart"] = lng
            session["step"] = "COURIER_DEST_TEXT"
            return build_response(
                "[▓▓▓▓░░░░░░] 40% · _Adresse de destination_\n\n"
                "✅ *Point de départ enregistré !*\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "📍 *Quelle est l'adresse de destination ?*\n\n"
                "_Exemple :_ `25 Rue Malanda, Poto-Poto`",
                ["🔙 Retour"]
            )
        
        # Cas 2: Client est au point d'arrivée (partage sa position = destination)
        if step == "COURIER_DEST_GPS" and lat and lng:
            nr["destination"] = "Position actuelle"
            nr["coordonnees_livraison"] = f"{lat},{lng}"
            nr["latitude_arrivee"] = lat
            nr["longitude_arrivee"] = lng
            session["step"] = "COURIER_DEPART_TEXT"
            return build_response(
                "[▓▓▓▓░░░░░░] 40% · _Adresse de départ_\n\n"
                "✅ *Point d'arrivée enregistré !*\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "📍 *Quelle est l'adresse de départ ?*\n\n"
                "_D'où le colis doit être récupéré_\n\n"
                "_Exemple :_ `10 Avenue de la Paix, BZV`",
                ["🔙 Retour"]
            )

    # Adresse de destination en texte (quand client est au départ)
    if step == "COURIER_DEST_TEXT":
        nr = session.setdefault("new_request", {})
        nr["destination"] = text
        session["step"] = "DEST_NOM"
        return build_response(
            "[▓▓▓▓▓▓░░░░] 60% · _Contact destinataire_\n\n"
            "👤 *Quel est le nom du destinataire ?*\n\n"
            "_La personne qui recevra le colis_\n\n"
            "_Exemple :_ `Marie Okemba`",
            ["🔙 Retour"]
        )
    
    # Adresse de départ en texte (quand client est à l'arrivée)
    if step == "COURIER_DEPART_TEXT":
        nr = session.setdefault("new_request", {})
        nr["depart"] = text
        session["step"] = "EXPEDITEUR_NOM"
        return build_response(
            "[▓▓▓▓▓▓░░░░] 60% · _Contact expéditeur_\n\n"
            "👤 *Quel est le nom de l'expéditeur ?*\n\n"
            "_La personne qui détient le colis_\n\n"
            "_Exemple :_ `Pierre Nkounkou`",
            ["🔙 Retour"]
        )

    # Nom du destinataire (quand client est au départ)
    if step == "DEST_NOM":
        session["new_request"]["destinataire_nom"] = text
        session["step"] = "DEST_TEL"
        return build_response("📞 Son *numéro de téléphone* ? (ex. `06 555 00 00`)", ["🔙 Retour"])
    
    # Nom de l'expéditeur (quand client est à l'arrivée)
    if step == "EXPEDITEUR_NOM":
        session["new_request"]["expediteur_nom"] = text
        session["step"] = "EXPEDITEUR_TEL"
        return build_response("📞 Son *numéro de téléphone* ? (ex. `06 555 00 00`)", ["🔙 Retour"])

    # Téléphone du destinataire (quand client est au départ)
    if step == "DEST_TEL":
        tel = re.sub(r"\s+", " ", text).strip()
        session["new_request"]["destinataire_tel"] = tel
        # Copier aussi vers contact_autre pour uniformiser
        session["new_request"]["contact_autre_nom"] = session["new_request"].get("destinataire_nom")
        session["new_request"]["contact_autre_tel"] = tel
        session["step"] = "COURIER_VALUE"
        return build_response(
            "[▓▓▓▓▓▓▓▓░░] 80% · _Détails du colis_\n\n"
            "💰 *Valeur estimée du colis* (en FCFA)\n\n"
            "_Cela nous permet d'assurer votre envoi_\n\n"
            "_Exemple :_ `5000`",
            ["🔙 Retour"]
        )
    
    # Téléphone de l'expéditeur (quand client est à l'arrivée)
    if step == "EXPEDITEUR_TEL":
        tel = re.sub(r"\s+", " ", text).strip()
        session["new_request"]["expediteur_tel"] = tel
        # On garde l'expéditeur dans destinataire_nom/tel pour l'API (car c'est le contact du colis)
        session["new_request"]["destinataire_nom"] = session["new_request"].get("expediteur_nom")
        session["new_request"]["destinataire_tel"] = tel
        session["step"] = "COURIER_VALUE"
        return build_response(
            "[▓▓▓▓▓▓▓▓░░] 80% · _Détails du colis_\n\n"
            "💰 *Valeur estimée du colis* (en FCFA)\n\n"
            "_Cela nous permet d'assurer votre envoi_\n\n"
            "_Exemple :_ `5000`",
            ["🔙 Retour"]
        )

    if step == "COURIER_VALUE":
        digits = re.sub(r"[^0-9]", "", text or "")
        amt = int(digits) if digits else None
        if not amt:
            return build_response(
                "⚠️ *Format incorrect*\n\n"
                "_Veuillez saisir uniquement des chiffres_\n\n"
                "_Exemple :_ `5000`",
                ["🔙 Retour"]
            )
        session["new_request"]["value_fcfa"] = amt
        session["step"] = "COURIER_DESC"
        return build_response(
            "[▓▓▓▓▓▓▓▓▓░] 90% · _Description_\n\n"
            "📦 *Décrivez brièvement le colis*\n\n"
            "_En quelques mots, que contient-il ?_\n\n"
            "_Exemple :_ `Documents A4, Paquet 2 kg`",
            ["🔙 Retour"]
        )

    if step == "COURIER_DESC":
        session["new_request"]["description"] = text
        session["step"] = "COURIER_CONFIRM"
        d = session["new_request"]
        
        # Affichage adapté selon la position du client
        client_position = d.get("client_position")
        dest_aff = "Position actuelle" if d.get("coordonnees_livraison") else d.get("destination", "—")
        depart_aff = "Position actuelle" if d.get("coordonnees_gps") else d.get("depart", "—")
        
        # Déterminer le contact à afficher
        if client_position == "arrivee":
            contact_label = "Expéditeur"
            contact_nom = d.get('expediteur_nom', '—')
            contact_tel = d.get('expediteur_tel', '—')
        else:
            contact_label = "Destinataire"
            contact_nom = d.get('destinataire_nom', '—')
            contact_tel = d.get('destinataire_tel', '—')
        
        recap = (
            "[▓▓▓▓▓▓▓▓▓▓] 100% · _Validation_\n\n"
            "*📝 RÉCAPITULATIF DE VOTRE DEMANDE*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "*🚏 Point de départ*\n"
            f"📍 _{depart_aff}_\n\n"
            "*🎯 Point d'arrivée*\n"
            f"📍 _{dest_aff}_\n\n"
            f"*👤 {contact_label}*\n"
            f"• Nom : *{contact_nom}*\n"
            f"• Tél : `{contact_tel}`\n\n"
            "*📦 Colis*\n"
            f"• Contenu : _{d.get('description', '—')}_\n"
            f"• Valeur : *{_fmt_fcfa(d.get('value_fcfa'))} FCFA*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "✅ _Tout est correct ?_"
        )
        return build_response(recap, ["✅ Confirmer", "✏️ Modifier", "🔙 Retour"])

    if step == "COURIER_CONFIRM":
        if t in {"confirmer", "oui", "ok"}:
            # message de transition doux
            return build_response("✨ Je finalise votre demande…") | courier_create(session)
        if t in {"annuler", "non"}:
            session["step"] = "MENU"
            session.pop("new_request", None)
            return build_response("✅ Demande annulée. Que souhaitez-vous faire ?", MAIN_MENU_BTNS)
        if t in {"modifier"}:
            session["step"] = "COURIER_EDIT"
            return build_response(
                "✏️ Que voulez-vous modifier ?",
                ["Départ", "Destination", "Destinataire", "Valeur", "Description"]
            )

    # Si l'utilisateur demande une modification précise (micro-raccourcis)
    if step == "COURIER_EDIT":
        choice = t
        if "départ" in choice:
            session["step"] = "COURIER_DEPART"
            return build_response("✏️ Modif *Départ* — envoyez la nouvelle adresse, ou partagez votre position.")
        if "destination" in choice:
            session["step"] = "COURIER_DEST"
            return build_response("✏️ Modif *Destination* — envoyez la nouvelle adresse, ou partagez la position.")
        if "destinataire" in choice:
            session["step"] = "DEST_NOM"
            return build_response("✏️ Modif *Destinataire* — quel est le *nom* ?")
        if "valeur" in choice:
            session["step"] = "COURIER_VALUE"
            return build_response("✏️ Modif *Valeur* — montant en FCFA (ex. `15000`).")
        if "description" in choice:
            session["step"] = "COURIER_DESC"
            return build_response("✏️ Modif *Description* — décrivez le colis en une phrase.")
        # si choix non reconnu
        return build_response(
            "Je n'ai pas compris. Que voulez-vous modifier ?",
            ["Départ", "Destination", "Destinataire", "Valeur", "Description"]
        )

    # Suivi de commande - L'utilisateur a saisi une référence
    if step == "FOLLOW_WAIT":
        return follow_lookup(session, text)

    # fallback IA (petite garde-fou UX)
    if text:
        return ai_fallback(text, session.get("phone"))
    return build_response("🤖 J’ai besoin d’une information pour continuer. Dites *Nouvelle demande* ou *Menu*.", MAIN_MENU_BTNS)

# --- Entrée principale ---
def handle_message(phone: str, text: str, lat: Optional[float] = None, lng: Optional[float] = None) -> Dict[str, Any]:
    session = get_session(phone)
    return flow_coursier_handle(session, text, lat=lat, lng=lng)

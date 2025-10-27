# chatbot/webhooks_notifications.py
"""
Webhooks pour déclencher automatiquement les notifications
À intégrer dans votre backend pour notifier les clients lors des changements de statut
"""

import logging
from typing import Dict, Any
from .notifications import (
    notify_mission_accepted,
    notify_pickup_arrived,
    notify_in_transit,
    notify_delivered,
    notify_order_confirmed,
    notify_order_ready
)

logger = logging.getLogger(__name__)


def on_mission_status_changed(mission_id: int, new_status: str, mission_data: Dict[str, Any]):
    """
    Appelé automatiquement quand le statut d'une mission change
    
    Args:
        mission_id: ID de la mission
        new_status: Nouveau statut (accepted, pickup_arrived, in_transit, delivered)
        mission_data: Données complètes de la mission (doit inclure contact_entreprise)
    
    Usage dans votre backend:
        # Dans votre API Django/Flask quand un livreur accepte une mission:
        from chatbot.webhooks_notifications import on_mission_status_changed
        
        mission = Mission.objects.get(id=mission_id)
        mission.status = 'accepted'
        mission.save()
        
        # Déclencher la notification automatiquement
        on_mission_status_changed(
            mission.id,
            'accepted',
            {
                'numero_mission': mission.numero_mission,
                'contact_entreprise': mission.contact_entreprise,  # Téléphone du client
                'livreur_nom': mission.livreur.nom,
                'livreur_telephone': mission.livreur.telephone,
                'adresse_recuperation': mission.adresse_recuperation,
                'adresse_livraison': mission.adresse_livraison,
                'valeur_produit': mission.valeur_produit,
                'nom_client_final': mission.nom_client_final
            }
        )
    """
    try:
        client_phone = mission_data.get("contact_entreprise")
        if not client_phone:
            logger.warning(f"[WEBHOOK] No client phone for mission {mission_id}")
            return False
        
        # Nettoyer le numéro (retirer le + si présent pour WhatsApp)
        if client_phone.startswith("+"):
            client_phone = client_phone[1:]
        
        # Déclencher la notification appropriée
        if new_status == "accepted" or new_status == "assigned":
            logger.info(f"[WEBHOOK] Triggering mission_accepted notification for mission {mission_id}")
            return notify_mission_accepted(client_phone, mission_data)
        
        elif new_status == "pickup_arrived" or new_status == "arrive_pickup":
            logger.info(f"[WEBHOOK] Triggering pickup_arrived notification for mission {mission_id}")
            return notify_pickup_arrived(client_phone, mission_data)
        
        elif new_status == "in_transit" or new_status == "en_route":
            logger.info(f"[WEBHOOK] Triggering in_transit notification for mission {mission_id}")
            return notify_in_transit(client_phone, mission_data)
        
        elif new_status == "delivered" or new_status == "livree" or new_status == "completed":
            logger.info(f"[WEBHOOK] Triggering delivered notification for mission {mission_id}")
            return notify_delivered(client_phone, mission_data)
        
        else:
            logger.info(f"[WEBHOOK] No notification for status: {new_status}")
            return False
    
    except Exception as e:
        logger.exception(f"[WEBHOOK] Error in on_mission_status_changed: {e}")
        return False


def on_order_status_changed(order_id: int, new_status: str, order_data: Dict[str, Any]):
    """
    Appelé automatiquement quand le statut d'une commande marketplace change
    
    Args:
        order_id: ID de la commande
        new_status: Nouveau statut (confirmed, ready, shipped, delivered)
        order_data: Données complètes de la commande (doit inclure client phone)
    
    Usage dans votre backend:
        from chatbot.webhooks_notifications import on_order_status_changed
        
        order = Commande.objects.get(id=order_id)
        order.status = 'confirmed'
        order.save()
        
        # Déclencher la notification
        on_order_status_changed(
            order.id,
            'confirmed',
            {
                'numero_commande': order.numero_commande,
                'client_phone': order.client.telephone,
                'entreprise_nom': order.entreprise.nom,
                'produit_nom': order.details.first().produit.nom,
                'quantite': order.details.first().quantite,
                'total': order.total,
                'adresse_retrait': order.entreprise.adresse
            }
        )
    """
    try:
        client_phone = order_data.get("client_phone") or order_data.get("telephone_client")
        if not client_phone:
            logger.warning(f"[WEBHOOK] No client phone for order {order_id}")
            return False
        
        # Nettoyer le numéro
        if client_phone.startswith("+"):
            client_phone = client_phone[1:]
        
        # Déclencher la notification appropriée
        if new_status == "confirmed" or new_status == "acceptee":
            logger.info(f"[WEBHOOK] Triggering order_confirmed notification for order {order_id}")
            return notify_order_confirmed(client_phone, order_data)
        
        elif new_status == "ready" or new_status == "prete":
            logger.info(f"[WEBHOOK] Triggering order_ready notification for order {order_id}")
            return notify_order_ready(client_phone, order_data)
        
        else:
            logger.info(f"[WEBHOOK] No notification for order status: {new_status}")
            return False
    
    except Exception as e:
        logger.exception(f"[WEBHOOK] Error in on_order_status_changed: {e}")
        return False


# === EXEMPLE D'INTÉGRATION DJANGO ===

"""
# Dans votre models.py ou signals.py Django:

from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Mission
from chatbot.webhooks_notifications import on_mission_status_changed

@receiver(post_save, sender=Mission)
def mission_status_changed(sender, instance, created, **kwargs):
    '''Signal déclenché automatiquement quand une mission est modifiée'''
    if not created:  # Seulement si c'est une modification, pas une création
        # Récupérer l'ancien statut
        try:
            old_instance = sender.objects.get(pk=instance.pk)
            if old_instance.statut != instance.statut:
                # Le statut a changé, déclencher la notification
                mission_data = {
                    'numero_mission': instance.numero_mission,
                    'contact_entreprise': instance.contact_entreprise,
                    'livreur_nom': instance.livreur.nom if instance.livreur else None,
                    'livreur_telephone': instance.livreur.telephone if instance.livreur else None,
                    'adresse_recuperation': instance.adresse_recuperation,
                    'adresse_livraison': instance.adresse_livraison,
                    'valeur_produit': str(instance.valeur_produit),
                    'nom_client_final': instance.nom_client_final
                }
                
                on_mission_status_changed(
                    instance.id,
                    instance.statut,
                    mission_data
                )
        except sender.DoesNotExist:
            pass
"""

# === EXEMPLE D'INTÉGRATION API REST ===

"""
# Dans votre API view (Django REST Framework):

from rest_framework.decorators import action
from rest_framework.response import Response
from chatbot.webhooks_notifications import on_mission_status_changed

class MissionViewSet(viewsets.ModelViewSet):
    queryset = Mission.objects.all()
    serializer_class = MissionSerializer
    
    @action(detail=True, methods=['post'])
    def update_status(self, request, pk=None):
        '''Endpoint pour mettre à jour le statut d'une mission'''
        mission = self.get_object()
        old_status = mission.statut
        new_status = request.data.get('status')
        
        if new_status:
            mission.statut = new_status
            mission.save()
            
            # Déclencher la notification automatiquement
            if old_status != new_status:
                mission_data = {
                    'numero_mission': mission.numero_mission,
                    'contact_entreprise': mission.contact_entreprise,
                    'livreur_nom': mission.livreur.nom if mission.livreur else None,
                    'livreur_telephone': mission.livreur.telephone if mission.livreur else None,
                    'adresse_recuperation': mission.adresse_recuperation,
                    'adresse_livraison': mission.adresse_livraison,
                    'valeur_produit': str(mission.valeur_produit),
                    'nom_client_final': mission.nom_client_final
                }
                
                on_mission_status_changed(mission.id, new_status, mission_data)
            
            return Response({'status': 'success', 'new_status': new_status})
        
        return Response({'error': 'No status provided'}, status=400)
"""


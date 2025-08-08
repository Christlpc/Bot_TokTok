from django.contrib import admin
from .models import (
    Client,
    Categorie,
    Produit,
    StatutLivraison,
    Livraison,
    TrackingGPS
)

@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('nom', 'telephone', 'email', 'date_inscription')
    search_fields = ('nom', 'telephone', 'email')

@admin.register(Categorie)
class CategorieAdmin(admin.ModelAdmin):
    list_display = ('nom', 'description')
    search_fields = ('nom',)

@admin.register(Produit)
class ProduitAdmin(admin.ModelAdmin):
    list_display = ('nom', 'categorie', 'poids_grammes')
    search_fields = ('nom',)
    list_filter = ('categorie',)

@admin.register(StatutLivraison)
class StatutLivraisonAdmin(admin.ModelAdmin):
    list_display = ('libelle',)
    search_fields = ('libelle',)

@admin.register(Livraison)
class LivraisonAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'client', 'produit', 'adresse_depart', 'adresse_arrivee',
        'date_demande', 'statut'
    )
    list_filter = ('statut', 'date_demande')
    search_fields = ('client__nom', 'produit__nom', 'adresse_depart', 'adresse_arrivee')

@admin.register(TrackingGPS)
class TrackingGPSAdmin(admin.ModelAdmin):
    list_display = ('livraison', 'latitude', 'longitude', 'timestamp')
    list_filter = ('timestamp',)

from django.db import models

class Client(models.Model):
    nom = models.CharField(max_length=100)
    telephone = models.CharField(max_length=20, unique=True)
    email = models.EmailField(blank=True, null=True)
    adresse = models.TextField(blank=True, null=True)
    date_inscription = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nom} - {self.telephone}"

class Categorie(models.Model):
    nom = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.nom

class Produit(models.Model):
    nom = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    poids_grammes = models.PositiveIntegerField()
    categorie = models.ForeignKey(Categorie, on_delete=models.SET_NULL, null=True)

    def __str__(self):
        return self.nom

class StatutLivraison(models.Model):
    libelle = models.CharField(max_length=100)

    def __str__(self):
        return self.libelle

class Livraison(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE)
    produit = models.ForeignKey(Produit, on_delete=models.CASCADE)
    adresse_depart = models.TextField()
    adresse_arrivee = models.TextField()
    date_demande = models.DateTimeField(auto_now_add=True)
    statut = models.ForeignKey(StatutLivraison, on_delete=models.SET_NULL, null=True)
    commentaire = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Livraison #{self.id} - {self.client.nom}"

class TrackingGPS(models.Model):
    livraison = models.ForeignKey(Livraison, on_delete=models.CASCADE, related_name='trackings')
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Tracking {self.livraison.id} @ {self.timestamp}"

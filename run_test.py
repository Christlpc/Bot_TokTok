import re
import chatbot.livreur_flow as bot

# --- Fake Response ---
class FakeResp:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text
    def json(self):
        return self._json
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}: {self.text}")

# --- Fixtures ---
MISSIONS = {
    "101": {
        "id": 101,
        "numero_mission": "M-101",
        "adresse_recuperation": "Poto-Poto",
        "coordonnees_recuperation": "-4.27,15.29",
        "adresse_livraison": "Moungali",
        "coordonnees_livraison": "-4.28,15.30",
        "type_paiement": "entreprise_paie",
        "statut": "assignee",
        "description_produit": "Colis A",
        "nom_client_final": "Client A",
        "telephone_client_final": "+242060000000"
    },
    "102": {
        "id": 102,
        "numero_mission": "M-102",
        "adresse_recuperation": "Talangai",
        "coordonnees_recuperation": "",
        "adresse_livraison": "Centre-ville",
        "coordonnees_livraison": "",
        "type_paiement": "prepayee",
        "statut": "assignee",
        "description_produit": "Colis B",
        "nom_client_final": "Client B",
        "telephone_client_final": "+242060000001"
    }
}
LIVRAISONS = {
    "101": {"id": 101, "statut":"assignee", "adresse_livraison":"Moungali"},
    "102": {"id": 102, "statut":"assignee", "adresse_livraison":"Centre-ville"}
}

# --- Monkeypatch requests used inside bot_module ---
def fake_post(url, json=None, headers=None, timeout=10, **kwargs):
    if url.endswith("/api/v1/auth/login/"):
        if json and json.get("password") == "secret123":
            return FakeResp(200, {"access":"tok_access","refresh":"tok_refresh"})
        return FakeResp(401, {"detail":"Invalid"})
    if url.endswith("/api/v1/auth/refresh/"):
        return FakeResp(200, {"access":"tok_access_new"})
    if url.endswith("/toggle_disponibilite/"):
        return FakeResp(200, {"ok": True})
    if "/update_statut/" in url:
        return FakeResp(200, {"ok": True})
    if "/update_position/" in url:
        return FakeResp(200, {"ok": True})
    if "/accepter/" in url:
        return FakeResp(200, {"ok": True})
    # Fallback IA
    if "/chat/completions" in url:
        return FakeResp(200, {"choices":[{"message":{"content":"Je peux t’aider à gérer tes missions. Essaie « Missions dispo » ou « Mes missions ». "}}]})
    return FakeResp(404, {"detail":"Not found"}, text="not found")

def fake_request(method, url, headers=None, timeout=10, **kwargs):
    if method.upper() == "GET":
        if url.endswith("/api/v1/auth/livreurs/my_profile/"):
            return FakeResp(200, {"id":7, "nom_complet":"Pierre Livreur","disponible":False})
        if url.endswith("/api/v1/coursier/missions/disponibles/"):
            return FakeResp(200, [MISSIONS["101"], MISSIONS["102"]])
        m = re.match(r".*/api/v1/coursier/missions/(\d+)/$", url)
        if m:
            mid = m.group(1)
            data = MISSIONS.get(mid)
            return FakeResp(200, data) if data else FakeResp(404, {})
        m = re.match(r".*/api/v1/livraisons/livraisons/(\d+)/$", url)
        if m:
            lid = m.group(1)
            data = LIVRAISONS.get(lid)
            return FakeResp(200, data) if data else FakeResp(404, {})
        if url.endswith("/api/v1/coursier/missions/mes_missions/"):
            arr = []
            for k,v in LIVRAISONS.items():
                if v.get("statut") != "assignee":
                    arr.append({"id": int(k), "statut": v["statut"], "adresse_livraison": v["adresse_livraison"]})
            return FakeResp(200, arr)
        if url.endswith("/api/v1/livraisons/livraisons/mes_livraisons/"):
            arr = [{"id": int(k), "statut": v["statut"], "adresse_livraison": v["adresse_livraison"]} for k,v in LIVRAISONS.items()]
            return FakeResp(200, arr)
    if method.upper() == "POST":
        return fake_post(url, **kwargs)
    return FakeResp(404, {}, text="not found")

# Appliquer le monkeypatch
bot.requests.post = fake_post
bot.requests.request = fake_request

def say(resp):
    txt = resp.get("response")
    btns = resp.get("buttons")
    if btns:
        print(txt + "\n[buttons] " + " | ".join(btns))
    else:
        print(txt)

def simulate():
    phone = "+242061234567"
    # 0. Welcome / Bonjour
    say(bot.handle_message(phone, "Bonjour"))
    # 1. Choix -> Connexion
    say(bot.handle_message(phone, "Connexion"))
    # 2. Mauvais mot de passe
    say(bot.handle_message(phone, "wrongpass"))
    # 3. Bon mot de passe
    say(bot.handle_message(phone, "secret123"))
    # 4. Missions dispo
    say(bot.handle_message(phone, "Missions dispo"))
    # 5. Détails mission
    say(bot.handle_message(phone, "Détails 101"))
    # 6. Accepter mission
    say(bot.handle_message(phone, "Accepter 101"))
    # 7. Démarrer
    say(bot.handle_message(phone, "Démarrer"))
    # 8. Arrivé pickup
    say(bot.handle_message(phone, "Arrivé pickup"))
    # 9. Arrivé livraison
    say(bot.handle_message(phone, "Arrivé livraison"))
    # 10. Livrée
    say(bot.handle_message(phone, "Livrée"))
    # 11. Message ambigu -> fallback IA
    say(bot.handle_message(phone, "peux-tu appeler le client pour moi ?"))

if __name__ == "__main__":
    simulate()

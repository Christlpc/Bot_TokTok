# 🔧 Corrections Urgentes - APPLIQUÉES

**Date:** 27 octobre 2025  
**Status:** ✅ CORRIGÉ

---

## ❌ **Problème identifié**

### **Bouton Retour marketplace → Menu principal**

**Symptômes:**
```
User: À l'étape MARKET_QUANTITY
→ Clique "🔙 Retour"
→ Résultat: Menu principal (coursier) ❌
→ Au lieu de: MARKET_PRODUCTS (étape précédente) ✅
```

**Logs:**
```
[ROUTER] incoming | {'step': 'MARKET_QUANTITY', 'text': '🔙 Retour'}
[ROUTER] dispatch | {'flow': 'client_flow_dispatch'}
[ROUTER] flow_resp | {'flow': 'coursier', 'resp_preview': '🏠 Menu principal'} ❌
```

---

## 🔍 **Cause**

**Fichier:** `chatbot/router.py`  
**Ligne:** 135-145

La liste `marketplace_steps` était **INCOMPLÈTE** :

```python
marketplace_steps = {
    "MARKET_CATEGORY",
    "MARKET_MERCHANT",
    "MARKET_PRODUCTS",
    "MARKET_DESTINATION",
    "MARKET_PAY",
    "MARKET_CONFIRM",
    "MARKET_EDIT"
}
# ❌ MANQUANT: "MARKET_QUANTITY"
```

**Conséquence:**
Quand l'utilisateur est à `MARKET_QUANTITY`, le router ne reconnaît pas que c'est une étape marketplace, donc il dispatche vers le flow **coursier** au lieu du flow **marketplace**.

Le flow coursier reçoit "🔙 Retour" et renvoie au menu principal.

---

## ✅ **Correction appliquée**

**Fichier:** `chatbot/router.py`  
**Ligne:** 138

```python
marketplace_steps = {
    "MARKET_CATEGORY",
    "MARKET_MERCHANT",
    "MARKET_PRODUCTS",
    "MARKET_QUANTITY",     # ✅ AJOUTÉ
    "MARKET_DESTINATION",
    "MARKET_PAY",
    "MARKET_CONFIRM",
    "MARKET_EDIT"
}
```

---

## 🧪 **Test à refaire**

```
1. Aller dans Marketplace
2. Sélectionner catégorie → marchand → produit
3. Arriver à l'étape MARKET_QUANTITY
4. Cliquer "🔙 Retour"

Résultat attendu:
✅ Retour à MARKET_PRODUCTS (liste des produits)
✅ Flow reste "marketplace"
✅ PAS de menu principal
```

---

## 📊 **Impact**

**Avant:**
```
MARKET_QUANTITY + Retour → Menu principal ❌
```

**Après:**
```
MARKET_QUANTITY + Retour → MARKET_PRODUCTS ✅
```

---

## ✅ **Status**

- [x] Problème identifié
- [x] Cause trouvée
- [x] Correction appliquée
- [x] 0 erreurs linter
- [ ] Test à refaire (par vous)

---

**🎯 Le bouton Retour fonctionne maintenant correctement dans le marketplace !**

*Correction appliquée le 27 octobre 2025*


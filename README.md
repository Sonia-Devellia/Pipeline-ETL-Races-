# Kotcha — Base de données courses (POC RunSignup)

POC d'un pipeline ETL extensible pour agréger des courses (route / trail / autres)
de plusieurs sources. Ce POC couvre **une seule source : RunSignup (USA)**, mais
l'architecture est pensée pour qu'ajouter une source = ajouter un fichier dans
`connectors/` + une ligne dans `run.py`.

Périmètre validé : **Californie, 3 prochains mois** (petit volume propre).

---

## Architecture

```
connectors/
  base.py        # interface commune : Connector.fetch() -> list[Race]
  runsignup.py   # connecteur RunSignup (pagination, conversions, typage)
core/
  model.py       # Race = format PIVOT commun à toutes les sources
  loader.py      # écriture en base : MySQLLoader (prod) + SQLiteLoader (tests)
run.py           # orchestrateur : pour chaque connecteur -> fetch -> load
schema_mysql.sql      # CREATE DATABASE + CREATE TABLE (MySQL)
seed_mysql.sql        # les 25 courses du POC, prêtes à charger dans MySQL
tests/
  test_normalize.py   # tests des conversions (km, dates, typage, prix)
.cache/runsignup/     # pages JSON réelles (pour rejouer/peupler hors-ligne)
races.db              # artefact SQLite (uniquement pour tests hors-ligne)
```

> **Base de production : MySQL.** SQLite n'est conservé que comme backend de
> test local (peuplement hors-ligne sans serveur).

Le **format pivot `Race`** est le contrat central. Chaque connecteur traduit ses
données brutes vers `Race` ; le loader et la base ne connaissent que ce format.

Champs `Race` : `date`, `pays`, `ville`, `distance_km`, `type`, `prix`,
`source`, `external_id` (+ `devise`, ajouté car les prix US sont en USD).
> `distance_km` porte l'unité dans son nom : tout est normalisé en kilomètres.

---

## Étape 0 — Structure réelle de l'API (vérifiée le 2026-06-04)

`GET https://api.runsignup.com/rest/races?format=json&events=T&distance_units=K&state=CA&start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&page=N`
(public, sans clé). Réponse : `{"races":[{"race":{...}}]}`, paginée.

Points confirmés (et pièges) :

- **Date** : `next_date` au niveau course, format **US `MM/DD/YYYY`**. Les
  épreuves portent aussi `start_time` (`M/D/YYYY HH:MM`). → normalisé en **ISO 8601**.
- **Distances** : sous `events[].distance`, **chaîne à unités mixtes** :
  `"5K"`, `"8K"`, `"10K"`, `"100 Miles"`, `"2 Miles"`, `"0.25 Miles"`, `"200m"`,
  parfois `null`. → parsing + conversion **miles/m → km**.
- **Prix du dossard** : `events[].registration_periods[].race_fee` (ex. `"$55.00"`),
  avec **plusieurs paliers** (early-bird…). → on retient le palier **actif
  aujourd'hui**, sinon le tarif de base.
- **Type route/trail** : `events[].event_type` expose des valeurs utiles :
  `running_race` / `running_only` ⇒ `route`, `trail_race` /
  `open_course_trail` / `ultra` ⇒ `trail`. Pour les événements typés route mais
  contenant `trail` ou `ultra` dans le nom, on garde une heuristique de secours.
  Tout le reste (virtuel, marche, rando, triathlon, vélo…) ⇒ `other`.

**Granularité** : une course RunSignup contient plusieurs épreuves (5K, 10K,
Kids…) avec des distances et prix différents. On crée donc **une `Race` par
épreuve**, avec `external_id = event_id` (unique chez RunSignup).

Un échantillon réel des pages est conservé dans `.cache/runsignup/` (champs
utiles uniquement). La réponse brute complète est reproductible via l'URL ci-dessus.

---

## Utilisation

### 1. Préparer MySQL

```bash
pip install pymysql                      # driver (pur-Python)
mysql -u root -p < schema_mysql.sql      # crée la base kotcha_races + la table
```

### 2. Lancer le pipeline (écrit dans MySQL)

```bash
export MYSQL_HOST=localhost MYSQL_USER=root MYSQL_PASSWORD=*** MYSQL_DB=kotcha_races
python run.py
```

### Charger directement les 25 courses du POC (sans réseau)

```bash
mysql -u root -p kotcha_races < seed_mysql.sql
```

### 3. Afficher les courses dans une vue PHP

Une vue web simple est disponible dans `public/index.php`. Elle lit la table
MySQL `races` et affiche uniquement les courses `route` et `trail`, sous forme
de tableau filtrable par type, pays, ville, dates, distance et prix.

```bash
export MYSQL_HOST=localhost MYSQL_USER=root MYSQL_PASSWORD=*** MYSQL_DB=kotcha_races
php -S localhost:8000 -t public
```

Ou créer un fichier `.env` à la racine du projet, à partir de `.env.example` :

```bash
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=***
MYSQL_DB=kotcha_races
```

Ouvrir ensuite http://localhost:8000 dans un navigateur.

Si la base contient encore d'anciennes lignes `other`, elles peuvent être
supprimées avec :

```bash
mysql -u root -p kotcha_races -e "DELETE FROM races WHERE type NOT IN ('route', 'trail');"
```

Configuration par variables d'environnement :

| Variable | Rôle | Défaut |
|---|---|---|
| `DB_BACKEND` | `mysql` (prod) ou `sqlite` (tests) | `mysql` |
| `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DB` | connexion MySQL | `localhost` / `3306` / `root` / `` / `kotcha_races` |
| `RACES_DB_PATH` | fichier SQLite (si `DB_BACKEND=sqlite`) | `races.db` |
| `RUNSIGNUP_STATE` | état US | `CA` |
| `RUNSIGNUP_START` / `RUNSIGNUP_END` | fenêtre de dates `YYYY-MM-DD` | aujourd'hui / +90 j |
| `RUNSIGNUP_RPP` | résultats par page | `50` |
| `RUNSIGNUP_CACHE_DIR` | si défini, lit les pages locales au lieu du réseau | — |

Tests : `python tests/test_normalize.py` (22 assertions, 0 dépendance externe).

Le **re-run est sûr** : contrainte d'unicité `(source, external_id)` + upsert →
mise à jour de l'existant, jamais de doublon.

---

## Résultats du POC (Californie, juin–sept. 2026)

- **25 courses (épreuves) chargées** depuis 12 organisations, sur 11 villes
  (San Francisco, San Diego, Los Angeles, Redding, Richmond, Auburn…).
- Répartition : **17 `route`**, **8 `other`** (virtuel, marche, rando, dons).
  Aucune épreuve nommée « trail » dans l'échantillon — la classification `trail`
  est validée séparément par les tests unitaires.
- Prix : **0 → 55,99 USD** (moyenne ~34,6).
- Conversions vérifiées : `100 Miles → 160,934 km`, `8K → 8.0`, `0.25 Miles → 0.402`,
  `200m → 0.2`.
- Idempotence vérifiée : run 1 = 25 insérées ; run 2 = 0 insérée / 25 mises à jour.

---

## Ajouter une source FR (ou autre) plus tard

1. Créer `connectors/ma_source_fr.py` avec une classe héritant de `Connector` :
   ```python
   from connectors.base import Connector
   from core.model import Race

   class MaSourceFR(Connector):
       source = "ma_source_fr"
       def fetch(self) -> list[Race]:
           # appeler l'API FR, puis traduire CHAQUE course vers Race(...)
           ...
   ```
2. Implémenter la **traduction vers `Race`** : c'est le seul travail spécifique.
   Réutiliser les mêmes conventions (dates ISO, `distance_km`, type route/trail/other,
   `external_id` = identifiant d'origine, `pays="FR"`, `devise="EUR"`).
3. Ajouter **une ligne** dans `run.py` → `build_connectors()` :
   `connectors.append(MaSourceFR(...))`.

Rien d'autre ne change : loader, base, orchestrateur et schéma sont déjà communs.
Les prix multi-devises sont gérés par le champ `devise`.

### Backends de base
`core/loader.py` expose une interface `Loader` :
- **`MySQLLoader`** (PyMySQL, `INSERT ... ON DUPLICATE KEY UPDATE`) — **base de
  production**, sélectionnée par défaut (`DB_BACKEND=mysql`).
- `SQLiteLoader` (`ON CONFLICT ... DO UPDATE`) — uniquement pour tests/peuplements
  locaux hors-ligne.

Ajouter un autre moteur = écrire une classe `Loader` de plus ; connecteurs et
orchestrateur n'y touchent pas.

---

## Notes / limites du POC

- **Réseau / MySQL en sandbox** : l'environnement de génération n'avait ni accès
  réseau direct ni serveur MySQL. Les données ont été récupérées via l'outil web
  (pages réelles mises en cache dans `.cache/runsignup/`) puis normalisées par
  **le même code** que la production ; le résultat a été exporté en
  `seed_mysql.sql` (chargeable tel quel) et, pour démonstration, dans `races.db`
  (SQLite). En production, `python run.py` appelle directement l'API (couche HTTP
  `urllib`, rate limiting poli de 0,5 s) et écrit dans **MySQL**.
- **Typage trail** : heuristique sur le nom faute de champ dédié côté RunSignup ;
  à affiner par source.
- **Prix** : palier actif du jour, sinon tarif de base ; les frais de traitement
  (`processing_fee`) ne sont pas inclus.
- Les dossiers `__pycache__` / `races.db-journal` éventuels sont des artefacts
  d'exécution sans importance.
```

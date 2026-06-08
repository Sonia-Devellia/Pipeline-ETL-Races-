<?php
declare(strict_types=1);

function load_dotenv(string $path): void
{
    if (!is_readable($path)) {
        return;
    }

    foreach (file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        $line = trim($line);
        if ($line === '' || str_starts_with($line, '#') || !str_contains($line, '=')) {
            continue;
        }

        [$key, $value] = array_map('trim', explode('=', $line, 2));
        if ($key === '' || getenv($key) !== false) {
            continue;
        }

        $value = trim($value, "\"'");
        putenv("{$key}={$value}");
        $_ENV[$key] = $value;
        $_SERVER[$key] = $value;
    }
}

function env_value(string $key, string $default = ''): string
{
    $value = getenv($key);
    return $value === false ? $default : $value;
}

function h(?string $value): string
{
    return htmlspecialchars((string) $value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function selected(?string $current, ?string $option): string
{
    return $current !== null && $current !== '' && $current === $option ? ' selected' : '';
}

function get_filter(string $key): ?string
{
    $value = $_GET[$key] ?? null;
    if (!is_string($value)) {
        return null;
    }

    $value = trim($value);
    return $value === '' ? null : $value;
}

load_dotenv(dirname(__DIR__) . '/.env');

$filters = [
    'nom' => get_filter('nom'),
    'type' => get_filter('type'),
    'pays' => get_filter('pays'),
    'ville' => get_filter('ville'),
    'date_debut' => get_filter('date_debut'),
    'date_fin' => get_filter('date_fin'),
    'distance_min' => get_filter('distance_min'),
    'distance_max' => get_filter('distance_max'),
    'prix_max' => get_filter('prix_max'),
];

$dbHost = env_value('MYSQL_HOST', 'localhost');
$dbName = env_value('MYSQL_DB', 'kotcha_races');
$dbUser = env_value('MYSQL_USER', 'root');
$dbPassword = env_value('MYSQL_PASSWORD', 'root');

$races = [];
$types = ['route', 'trail'];
$countries = [];
$cities = [];
$error = null;

try {
    $dsn = "mysql:host={$dbHost};dbname={$dbName};charset=utf8mb4";
    $pdo = new PDO($dsn, $dbUser, $dbPassword, [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        PDO::ATTR_EMULATE_PREPARES => false,
    ]);

    $countries = $pdo->query("SELECT DISTINCT pays FROM races WHERE type IN ('route', 'trail') AND pays IS NOT NULL AND pays <> '' ORDER BY pays")
        ->fetchAll(PDO::FETCH_COLUMN);
    $cities = $pdo->query("SELECT DISTINCT ville FROM races WHERE type IN ('route', 'trail') AND ville IS NOT NULL AND ville <> '' ORDER BY ville")
        ->fetchAll(PDO::FETCH_COLUMN);

    $where = ["type IN ('route', 'trail')"];
    $params = [];

    if ($filters['nom']) {
        $where[] = 'nom LIKE :nom';
        $params['nom'] = '%' . $filters['nom'] . '%';
    }
    if ($filters['type'] && in_array($filters['type'], $types, true)) {
        $where[] = 'type = :type';
        $params['type'] = $filters['type'];
    }
    if ($filters['pays']) {
        $where[] = 'pays = :pays';
        $params['pays'] = $filters['pays'];
    }
    if ($filters['ville']) {
        $where[] = 'ville = :ville';
        $params['ville'] = $filters['ville'];
    }
    if ($filters['date_debut']) {
        $where[] = 'date >= :date_debut';
        $params['date_debut'] = $filters['date_debut'];
    }
    if ($filters['date_fin']) {
        $where[] = 'date <= :date_fin';
        $params['date_fin'] = $filters['date_fin'];
    }
    if ($filters['distance_min'] !== null) {
        $where[] = 'distance_km >= :distance_min';
        $params['distance_min'] = $filters['distance_min'];
    }
    if ($filters['distance_max'] !== null) {
        $where[] = 'distance_km <= :distance_max';
        $params['distance_max'] = $filters['distance_max'];
    }
    if ($filters['prix_max'] !== null) {
        $where[] = 'prix <= :prix_max';
        $params['prix_max'] = $filters['prix_max'];
    }

    $sql = "
        SELECT nom, url, type, pays, ville, date, distance_km, prix, devise, source
        FROM races
    ";
    if ($where) {
        $sql .= ' WHERE ' . implode(' AND ', $where);
    }
    $sql .= ' ORDER BY date IS NULL, date ASC, pays ASC, ville ASC, distance_km ASC LIMIT 500';

    $stmt = $pdo->prepare($sql);
    $stmt->execute($params);
    $races = $stmt->fetchAll();
} catch (Throwable $exception) {
    $error = $exception->getMessage();
}

?>
<!doctype html>
<html lang="fr">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>BDD Races - Courses</title>
    <style>
        :root {
            color-scheme: light;
            --bg: #f6f7f9;
            --panel: #ffffff;
            --text: #17202a;
            --muted: #687586;
            --line: #d9dee7;
            --accent: #1f7a5c;
            --accent-dark: #145943;
            --danger-bg: #fff1f1;
            --danger-text: #8a1f1f;
        }

        * {
            box-sizing: border-box;
        }

        body {
            margin: 0;
            background: var(--bg);
            color: var(--text);
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            line-height: 1.45;
        }

        main {
            width: min(1180px, calc(100% - 32px));
            margin: 32px auto;
        }

        header {
            display: flex;
            align-items: flex-end;
            justify-content: space-between;
            gap: 24px;
            margin-bottom: 22px;
        }

        h1 {
            margin: 0 0 4px;
            font-size: clamp(1.65rem, 3vw, 2.4rem);
            font-weight: 750;
        }

        .subtitle {
            margin: 0;
            color: var(--muted);
        }

        .count {
            flex: 0 0 auto;
            color: var(--muted);
            font-weight: 600;
        }

        .filters,
        .table-wrap,
        .alert {
            background: var(--panel);
            border: 1px solid var(--line);
            border-radius: 8px;
        }

        .filters {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 14px;
            padding: 18px;
            margin-bottom: 18px;
        }

        label {
            display: grid;
            gap: 6px;
            color: var(--muted);
            font-size: 0.9rem;
            font-weight: 650;
        }

        select,
        input {
            width: 100%;
            min-height: 40px;
            border: 1px solid var(--line);
            border-radius: 6px;
            background: #fff;
            color: var(--text);
            padding: 8px 10px;
            font: inherit;
        }

        .actions {
            display: flex;
            align-items: end;
            gap: 10px;
        }

        button,
        .reset {
            min-height: 40px;
            border-radius: 6px;
            padding: 9px 14px;
            font: inherit;
            font-weight: 700;
            text-decoration: none;
            cursor: pointer;
        }

        button {
            border: 1px solid var(--accent);
            background: var(--accent);
            color: #fff;
        }

        button:hover {
            background: var(--accent-dark);
            border-color: var(--accent-dark);
        }

        .reset {
            border: 1px solid var(--line);
            color: var(--text);
            background: #fff;
        }

        .table-wrap {
            overflow-x: auto;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            min-width: 840px;
        }

        th,
        td {
            padding: 13px 14px;
            border-bottom: 1px solid var(--line);
            text-align: left;
            vertical-align: middle;
            white-space: nowrap;
        }

        th {
            background: #eef2f5;
            color: #394655;
            font-size: 0.82rem;
            letter-spacing: 0;
            text-transform: uppercase;
        }

        tbody tr:hover {
            background: #f9fbfa;
        }

        tbody tr:last-child td {
            border-bottom: 0;
        }

        .badge {
            display: inline-flex;
            align-items: center;
            min-height: 24px;
            border-radius: 999px;
            background: #e7f3ee;
            color: #155c45;
            padding: 3px 9px;
            font-size: 0.84rem;
            font-weight: 750;
        }

        .name-cell {
            white-space: normal;
            min-width: 220px;
            max-width: 360px;
            font-weight: 650;
        }

        .name-cell a {
            color: var(--accent-dark);
            text-decoration: none;
        }

        .name-cell a:hover {
            text-decoration: underline;
        }

        .muted {
            color: var(--muted);
        }

        .empty {
            padding: 32px 18px;
            text-align: center;
            color: var(--muted);
        }

        .alert {
            padding: 16px;
            background: var(--danger-bg);
            color: var(--danger-text);
            border-color: #f0b9b9;
        }

        @media (max-width: 900px) {
            header {
                display: block;
            }

            .count {
                margin-top: 10px;
            }

            .filters {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }

        @media (max-width: 620px) {
            main {
                width: min(100% - 20px, 1180px);
                margin: 18px auto;
            }

            .filters {
                grid-template-columns: 1fr;
                padding: 14px;
            }

            .actions {
                align-items: stretch;
                flex-direction: column;
            }
        }
    </style>
</head>
<body>
<main>
    <header>
        <div>
            <h1>Courses</h1>
            <p class="subtitle">Vue filtrable connectée à la table MySQL <code>races</code>.</p>
        </div>
        <?php if (!$error): ?>
            <div class="count"><?= count($races) ?> résultat<?= count($races) > 1 ? 's' : '' ?></div>
        <?php endif; ?>
    </header>

    <?php if ($error): ?>
        <div class="alert">
            Connexion impossible à MySQL. Vérifiez <code>MYSQL_HOST</code>, <code>MYSQL_USER</code>,
            <code>MYSQL_PASSWORD</code> et <code>MYSQL_DB</code>.<br>
            <strong>Détail :</strong> <?= h($error) ?>
        </div>
    <?php else: ?>
        <form class="filters" method="get">
            <label>
                Nom de la course
                <input type="search" name="nom" placeholder="ex. Marathon de Paris"
                       value="<?= h($filters['nom']) ?>">
            </label>

            <label>
                Type
                <select name="type">
                    <option value="">Tous</option>
                    <?php foreach ($types as $type): ?>
                        <option value="<?= h($type) ?>"<?= selected($filters['type'], $type) ?>><?= h($type) ?></option>
                    <?php endforeach; ?>
                </select>
            </label>

            <label>
                Pays
                <select name="pays">
                    <option value="">Tous</option>
                    <?php foreach ($countries as $country): ?>
                        <option value="<?= h($country) ?>"<?= selected($filters['pays'], $country) ?>><?= h($country) ?></option>
                    <?php endforeach; ?>
                </select>
            </label>

            <label>
                Ville
                <select name="ville">
                    <option value="">Toutes</option>
                    <?php foreach ($cities as $city): ?>
                        <option value="<?= h($city) ?>"<?= selected($filters['ville'], $city) ?>><?= h($city) ?></option>
                    <?php endforeach; ?>
                </select>
            </label>

            <label>
                Date début
                <input type="date" name="date_debut" value="<?= h($filters['date_debut']) ?>">
            </label>

            <label>
                Date fin
                <input type="date" name="date_fin" value="<?= h($filters['date_fin']) ?>">
            </label>

            <label>
                Distance min. km
                <input type="number" step="0.1" min="0" name="distance_min" value="<?= h($filters['distance_min']) ?>">
            </label>

            <label>
                Distance max. km
                <input type="number" step="0.1" min="0" name="distance_max" value="<?= h($filters['distance_max']) ?>">
            </label>

            <label>
                Prix max.
                <input type="number" step="0.01" min="0" name="prix_max" value="<?= h($filters['prix_max']) ?>">
            </label>

            <div class="actions">
                <button type="submit">Filtrer</button>
                <a class="reset" href="<?= h(strtok($_SERVER['REQUEST_URI'], '?') ?: '/') ?>">Réinitialiser</a>
            </div>
        </form>

        <section class="table-wrap">
            <?php if (!$races): ?>
                <div class="empty">Aucune course ne correspond aux filtres.</div>
            <?php else: ?>
                <table>
                    <thead>
                    <tr>
                        <th>Course</th>
                        <th>Type</th>
                        <th>Pays</th>
                        <th>Ville</th>
                        <th>Date</th>
                        <th>Distance</th>
                        <th>Prix</th>
                        <th>Source</th>
                    </tr>
                    </thead>
                    <tbody>
                    <?php foreach ($races as $race): ?>
                        <tr>
                            <td class="name-cell">
                                <?php if (!empty($race['nom'])): ?>
                                    <?php if (!empty($race['url'])): ?>
                                        <a href="<?= h($race['url']) ?>" target="_blank" rel="noopener noreferrer"><?= h($race['nom']) ?></a>
                                    <?php else: ?>
                                        <?= h($race['nom']) ?>
                                    <?php endif; ?>
                                <?php else: ?>
                                    <span class="muted">-</span>
                                <?php endif; ?>
                            </td>
                            <td><span class="badge"><?= h($race['type']) ?></span></td>
                            <td><?= h($race['pays']) ?: '<span class="muted">-</span>' ?></td>
                            <td><?= h($race['ville']) ?: '<span class="muted">-</span>' ?></td>
                            <td><?= h($race['date']) ?: '<span class="muted">-</span>' ?></td>
                            <td>
                                <?php if ($race['distance_km'] !== null): ?>
                                    <?= h(number_format((float) $race['distance_km'], 2, ',', ' ')) ?> km
                                <?php else: ?>
                                    <span class="muted">-</span>
                                <?php endif; ?>
                            </td>
                            <td>
                                <?php if ($race['prix'] !== null): ?>
                                    <?= h(number_format((float) $race['prix'], 2, ',', ' ')) ?>
                                    <?= h($race['devise']) ?>
                                <?php else: ?>
                                    <span class="muted">-</span>
                                <?php endif; ?>
                            </td>
                            <td><?= h($race['source']) ?></td>
                        </tr>
                    <?php endforeach; ?>
                    </tbody>
                </table>
            <?php endif; ?>
        </section>
    <?php endif; ?>
</main>
</body>
</html>

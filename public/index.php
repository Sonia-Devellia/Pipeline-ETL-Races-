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

function distance_label(?float $km, ?string $nom): string
{
    if ($km !== null) {
        $formatted = number_format($km, 2, ',', ' ');
        // Remove trailing zeros after comma
        $formatted = rtrim(rtrim($formatted, '0'), ',');
        return $formatted . ' km';
    }

    if ($nom === null) {
        return '';
    }

    $sub = strpos($nom, '–') !== false
        ? trim(substr($nom, strrpos($nom, '–') + strlen('–')))
        : $nom;

    $patterns = [
        '/\bhalf.{0,6}marathon\b/i' => 'Half Marathon',
        '/\bmarathon\b/i'           => 'Marathon',
        '/\bultra\b/i'              => 'Ultra',
        '/\b100\s?[Kk]\b/'         => '100K',
        '/\b50\s?[Kk]\b/'          => '50K',
        '/\b100.{0,3}[Mm]ile/i'    => '100 Miles',
        '/\b50.{0,3}[Mm]ile/i'     => '50 Miles',
    ];

    foreach ($patterns as $regex => $label) {
        if (preg_match($regex, $sub)) {
            return $label;
        }
    }

    return '';
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
    'source' => get_filter('source'),
    'type' => get_filter('type'),
    'pays' => get_filter('pays'),
    'ville' => get_filter('ville'),
    'date_debut' => get_filter('date_debut'),
    'date_fin' => get_filter('date_fin'),
    'distance_min' => get_filter('distance_min'),
    'distance_max' => get_filter('distance_max'),
    'prix_max' => get_filter('prix_max'),
];

$perPage = 100;
$currentPage = max(1, (int) ($_GET['page'] ?? 1));

$dbHost = env_value('MYSQL_HOST', 'localhost');
$dbName = env_value('MYSQL_DB', 'kotcha_races');
$dbUser = env_value('MYSQL_USER', 'root');
$dbPassword = env_value('MYSQL_PASSWORD', 'root');

$races = [];
$totalRaces = 0;
$totalPages = 1;
$types = ['route', 'trail'];
$countries = [];
$cities = [];
$sources = [];
$sourceCounts = [];
$error = null;

// Libellés lisibles pour les sources (API).
$sourceLabels = [
    'runsignup' => 'RunSignup',
    'active' => 'ACTIVE',
    'athlinks' => 'Athlinks',
];

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
    $sources = $pdo->query("SELECT DISTINCT source FROM races WHERE type IN ('route', 'trail') AND source IS NOT NULL AND source <> '' ORDER BY source")
        ->fetchAll(PDO::FETCH_COLUMN);
    $sourceCounts = $pdo->query("SELECT source, COUNT(*) AS n FROM races WHERE type IN ('route', 'trail') GROUP BY source ORDER BY n DESC")
        ->fetchAll(PDO::FETCH_KEY_PAIR);

    $where = ["type IN ('route', 'trail')"];
    $params = [];

    if ($filters['nom']) {
        $where[] = 'nom LIKE :nom';
        $params['nom'] = '%' . $filters['nom'] . '%';
    }
    if ($filters['source'] && in_array($filters['source'], $sources, true)) {
        $where[] = 'source = :source';
        $params['source'] = $filters['source'];
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

    $whereClause = $where ? ' WHERE ' . implode(' AND ', $where) : '';

    $countStmt = $pdo->prepare("SELECT COUNT(*) FROM races" . $whereClause);
    $countStmt->execute($params);
    $totalRaces = (int) $countStmt->fetchColumn();
    $totalPages = max(1, (int) ceil($totalRaces / $perPage));
    $currentPage = min($currentPage, $totalPages);
    $offset = ($currentPage - 1) * $perPage;

    $sql = "
        SELECT nom, url, type, pays, ville, date, distance_km, prix, devise, source
        FROM races
    " . $whereClause . "
        ORDER BY date IS NULL, date ASC, pays ASC, ville ASC, distance_km ASC
        LIMIT :limit OFFSET :offset
    ";

    $stmt = $pdo->prepare($sql);
    foreach ($params as $key => $value) {
        $stmt->bindValue($key, $value);
    }
    $stmt->bindValue('limit', $perPage, PDO::PARAM_INT);
    $stmt->bindValue('offset', $offset, PDO::PARAM_INT);
    $stmt->execute();
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

        .sources {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 8px;
            margin: -8px 0 18px;
        }

        .sources-label {
            color: var(--muted);
            font-weight: 650;
            font-size: 0.9rem;
        }

        .source-pill {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: var(--panel);
            border: 1px solid var(--line);
            border-radius: 999px;
            padding: 4px 11px;
            font-size: 0.85rem;
            color: var(--muted);
        }

        .source-pill strong {
            color: var(--accent-dark);
        }

        .source-tag {
            display: inline-block;
            font-size: 0.82rem;
            color: var(--muted);
        }

        .dist-label {
            font-size: 0.82rem;
            color: var(--muted);
            font-style: italic;
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

        .pagination {
            display: flex;
            align-items: center;
            justify-content: center;
            flex-wrap: wrap;
            gap: 6px;
            margin-top: 20px;
        }

        .pagination a,
        .pagination span {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 36px;
            min-height: 36px;
            border-radius: 6px;
            border: 1px solid var(--line);
            background: var(--panel);
            color: var(--text);
            font-size: 0.9rem;
            font-weight: 600;
            padding: 4px 10px;
            text-decoration: none;
        }

        .pagination a:hover {
            background: #f0f4f8;
            border-color: #b0bac6;
        }

        .pagination .current {
            background: var(--accent);
            border-color: var(--accent);
            color: #fff;
        }

        .pagination .disabled {
            opacity: 0.4;
            pointer-events: none;
        }

        .pagination-info {
            text-align: center;
            color: var(--muted);
            font-size: 0.88rem;
            margin-top: 10px;
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
            <div class="count"><?= number_format($totalRaces, 0, ',', ' ') ?> résultat<?= $totalRaces > 1 ? 's' : '' ?></div>
        <?php endif; ?>
    </header>

    <?php if (!$error && $sourceCounts): ?>
        <div class="sources">
            <span class="sources-label">Sources :</span>
            <?php foreach ($sourceCounts as $src => $n): ?>
                <span class="source-pill">
                    <?= h($sourceLabels[$src] ?? $src) ?>
                    <strong><?= (int) $n ?></strong>
                </span>
            <?php endforeach; ?>
        </div>
    <?php endif; ?>

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
                Source (API)
                <select name="source">
                    <option value="">Toutes</option>
                    <?php foreach ($sources as $src): ?>
                        <option value="<?= h($src) ?>"<?= selected($filters['source'], $src) ?>><?= h($sourceLabels[$src] ?? $src) ?></option>
                    <?php endforeach; ?>
                </select>
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
                                <?php
                                    $distLabel = distance_label(
                                        $race['distance_km'] !== null ? (float) $race['distance_km'] : null,
                                        $race['nom'] ?? null
                                    );
                                ?>
                                <?php if ($distLabel !== ''): ?>
                                    <?php if ($race['distance_km'] !== null): ?>
                                        <?= h($distLabel) ?>
                                    <?php else: ?>
                                        <span class="dist-label"><?= h($distLabel) ?></span>
                                    <?php endif; ?>
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
                            <td><span class="source-tag"><?= h($sourceLabels[$race['source']] ?? $race['source']) ?></span></td>
                        </tr>
                    <?php endforeach; ?>
                    </tbody>
                </table>
            <?php endif; ?>
        </section>

        <?php if ($totalPages > 1): ?>
            <?php
                $baseParams = array_filter($filters, fn($v) => $v !== null);
                function pagination_url(array $baseParams, int $page): string {
                    $q = array_merge($baseParams, ['page' => $page]);
                    return '?' . http_build_query($q);
                }
                $start = max(1, $currentPage - 3);
                $end   = min($totalPages, $currentPage + 3);
            ?>
            <nav class="pagination" aria-label="Pagination">
                <?php if ($currentPage > 1): ?>
                    <a href="<?= h(pagination_url($baseParams, 1)) ?>" title="Première page">&laquo;</a>
                    <a href="<?= h(pagination_url($baseParams, $currentPage - 1)) ?>">&lsaquo; Préc.</a>
                <?php else: ?>
                    <span class="disabled">&laquo;</span>
                    <span class="disabled">&lsaquo; Préc.</span>
                <?php endif; ?>

                <?php if ($start > 1): ?>
                    <a href="<?= h(pagination_url($baseParams, 1)) ?>">1</a>
                    <?php if ($start > 2): ?><span class="disabled">&hellip;</span><?php endif; ?>
                <?php endif; ?>

                <?php for ($p = $start; $p <= $end; $p++): ?>
                    <?php if ($p === $currentPage): ?>
                        <span class="current"><?= $p ?></span>
                    <?php else: ?>
                        <a href="<?= h(pagination_url($baseParams, $p)) ?>"><?= $p ?></a>
                    <?php endif; ?>
                <?php endfor; ?>

                <?php if ($end < $totalPages): ?>
                    <?php if ($end < $totalPages - 1): ?><span class="disabled">&hellip;</span><?php endif; ?>
                    <a href="<?= h(pagination_url($baseParams, $totalPages)) ?>"><?= $totalPages ?></a>
                <?php endif; ?>

                <?php if ($currentPage < $totalPages): ?>
                    <a href="<?= h(pagination_url($baseParams, $currentPage + 1)) ?>">Suiv. &rsaquo;</a>
                    <a href="<?= h(pagination_url($baseParams, $totalPages)) ?>" title="Dernière page">&raquo;</a>
                <?php else: ?>
                    <span class="disabled">Suiv. &rsaquo;</span>
                    <span class="disabled">&raquo;</span>
                <?php endif; ?>
            </nav>
            <p class="pagination-info">
                Page <?= $currentPage ?> / <?= $totalPages ?>
                &mdash; courses <?= number_format(($currentPage - 1) * $perPage + 1, 0, ',', ' ') ?>
                à <?= number_format(min($currentPage * $perPage, $totalRaces), 0, ',', ' ') ?>
                sur <?= number_format($totalRaces, 0, ',', ' ') ?>
            </p>
        <?php endif; ?>
    <?php endif; ?>
</main>
</body>
</html>

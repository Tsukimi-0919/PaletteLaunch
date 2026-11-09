// ==========================================================================
// PaletteLaunch UI
//
// 注意: 名前やパスなどの保存データは、innerHTML やインラインのイベント属性に
// 入れないこと。要素は createElement + textContent + addEventListener で組み立てる。
// ==========================================================================

const DEFAULT_THEME = 'valorant';
const DEFAULT_LANGUAGE = 'ja';
const ALLOWED_LANGUAGES = ['ja', 'en'];
const ALLOWED_CARD_SIZES = ['small', 'medium'];
const SIZE_CLASSES = ['size-small', 'size-medium', 'size-large'];
// Python 側（icons.py）が生成する形式のみ許可する
const ICON_SRC_PATTERN = /^data:image\/webp;base64,[A-Za-z0-9+/]+={0,2}$/;

let i18n = {}; // 翻訳データを保持する変数
let availableThemes = []; // get_themes() の結果
let initialized = false;

// 描画の直列化（実行中に呼ばれたら、終わったあとに1回だけ描き直す）
let renderRunning = null;
let renderRequested = false;
// Sortable のインスタンス（カテゴリー用は1つだけ、グリッド用は描き直すたびに destroy する）
let categorySortable = null;
let gridSortables = [];
// 起動の連打防止（全カード共通）
const LAUNCH_COOLDOWN_MS = 1000;
let launchLockedUntil = 0;
// ドロップ先のカテゴリー（Python 側の通知 paletteLaunchOnDrop と組み合わせる）
const DROP_TARGET_TTL_MS = 30000;
let pendingDrop = null;

// --- 入力値の正規化 -----------------------------------------------------------

function normalizeTheme(themeName) {
    return availableThemes.includes(themeName) ? themeName : DEFAULT_THEME;
}

function normalizeLanguage(langCode) {
    return ALLOWED_LANGUAGES.includes(langCode) ? langCode : DEFAULT_LANGUAGE;
}

function normalizeCardSize(size) {
    return ALLOWED_CARD_SIZES.includes(size) ? size : 'medium';
}

function applyCardSizeClass(container, size) {
    container.classList.remove(...SIZE_CLASSES);
    container.classList.add(`size-${size}`);
}

// --- 初期化 -------------------------------------------------------------------

async function init() {
    if (initialized) return;
    initialized = true;
    console.log("Pythonとの通信準備完了");
    await renderApp();
    await loadAndApplySettings();
    await notifyLoadStatus();
}

// --- 設定ファイルの状態の通知（alert のみ。保存データは innerHTML に入れない） ---

// 起動時に、読み取り専用モード・バックアップからの復元などを知らせる
async function notifyLoadStatus() {
    const status = await pywebview.api.get_load_status();
    if (!status) return;
    const lines = [];
    if (status.read_only) lines.push(i18n.notice_read_only);
    else if (status.restored_from_backup) lines.push(i18n.notice_restored);
    else if (status.reason === 'empty') lines.push(i18n.notice_recreated);
    if (lines.length && status.corrupt_copy) {
        lines.push(String(i18n.notice_corrupt_copy || '').split('{file}').join(String(status.corrupt_copy)));
    }
    if (lines.length) alert(lines.join('\n\n'));
}

// 保存できなかった操作を知らせる（読み取り専用モードか、書き込みの失敗か）
async function reportSaveFailure() {
    let status = null;
    try {
        status = await pywebview.api.get_load_status();
    } catch (e) {
        console.error(e);
    }
    alert(status && status.read_only ? i18n.error_read_only : i18n.error_save_failed);
}

function bindStaticHandlers() {
    // ページ全体でファイルのドロップを受け付ける（drop イベントを発生させるため）。
    // カテゴリー外にドロップしたときは pendingDrop を消して、追加しない。
    document.addEventListener('dragover', (e) => e.preventDefault());
    document.addEventListener('drop', (e) => {
        e.preventDefault();
        if (!e.target.closest || !e.target.closest('.shortcut-grid')) pendingDrop = null;
    });
    document.getElementById('lang-select')
        .addEventListener('change', (event) => changeLanguage(event.target.value));
    document.getElementById('theme-select')
        .addEventListener('change', (event) => changeTheme(event.target.value));
    document.querySelector('.add-cat-btn')
        .addEventListener('click', () => addCategory());
    document.getElementById('card-size-select')
        .addEventListener('change', async (event) => {
            const newSize = normalizeCardSize(event.target.value);
            if (!(await pywebview.api.update_setting('card_size', newSize))) await reportSaveFailure();
            await loadAndApplySettings();
        });
}

// --- 描画 ---------------------------------------------------------------------

// renderApp は直列化して呼ぶ（同時に2つ走らせない）
function renderApp() {
    if (renderRunning) {
        renderRequested = true;
        return renderRunning;
    }
    renderRunning = (async () => {
        try {
            do {
                renderRequested = false;
                await renderAppOnce();
            } while (renderRequested);
        } finally {
            renderRunning = null;
        }
    })();
    return renderRunning;
}

async function renderAppOnce() {
    // テーマを取得
    await initThemeSelector();
    const container = document.getElementById('app-container');

    // 1. Pythonから最新のデータを取得
    const fullData = await pywebview.api.get_config();

    // 2. データを分解
    const categories = fullData.categories;
    // テーマ切り替えで使用
    const appConfig = fullData.config;

    applyCardSizeClass(container, normalizeCardSize(appConfig.card_size));

    // 言語をロード（設定されている言語、なければ 'ja'）
    const language = normalizeLanguage(appConfig.language);
    await loadLanguage(language);

    // セレクトボックスの値を現在の設定に合わせる
    document.getElementById('lang-select').value = language;

    // 古いグリッドの Sortable を片付けてから作り直す
    gridSortables.forEach(sortable => sortable.destroy());
    gridSortables = [];
    container.replaceChildren();

    categories.forEach(category => {
        const catElement = createCategoryElement(category);
        container.appendChild(catElement);
    });

    // Sortable（カテゴリー用）。container は作り直さないので初回だけ生成する
    if (!categorySortable) {
        categorySortable = new Sortable(container, {
            animation: 150,
            handle: '.category-header',
            onEnd: async () => { await syncOrder(); }
        });
    }

    // テーマの適用
    applyTheme(appConfig.theme);
}

function createCategoryElement(category) {
    const catElement = document.createElement('section');
    catElement.className = 'category-section';

    // --- ヘッダー ---
    const header = document.createElement('div');
    header.className = 'category-header';

    const title = document.createElement('h2');
    title.className = 'category-title';
    title.style.cursor = 'pointer';
    title.title = i18n.prompt_edit_category;
    title.textContent = category.name;
    title.addEventListener('click', () => renameCategory(category.id, category.name));

    const actions = document.createElement('div');
    actions.className = 'category-actions';

    const addBtn = document.createElement('button');
    addBtn.className = 'action-btn';
    addBtn.textContent = i18n.add_app;
    addBtn.addEventListener('click', () => addShortcut(category.id));

    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'action-btn delete-cat';
    deleteBtn.textContent = i18n.delete;
    deleteBtn.addEventListener('click', () => removeCategory(category.id));

    // ボタン間の空白（以前のテンプレートの改行と同じ見た目の隙間を保つ）
    actions.append(addBtn, document.createTextNode(' '), deleteBtn);
    header.append(title, actions);

    // --- グリッド ---
    const gridElement = document.createElement('div');
    gridElement.className = 'shortcut-grid';
    gridElement.id = `grid-${category.id}`;

    catElement.append(header, gridElement);

    // --- ドラッグ＆ドロップイベント ---
    gridElement.addEventListener('dragover', (e) => { e.preventDefault(); gridElement.classList.add('drag-over'); });
    gridElement.addEventListener('dragleave', () => { gridElement.classList.remove('drag-over'); });
    gridElement.addEventListener('drop', (e) => {
        e.preventDefault();
        gridElement.classList.remove('drag-over');
        // フルパスは Python 側で受け取り、paletteLaunchOnDrop で知らされる（WebView2 には file.path が無い）
        if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
            pendingDrop = { categoryId: category.id, at: Date.now() };
        }
    });

    // --- ショートカットの表示処理 ---
    category.shortcuts.forEach(item => {
        gridElement.appendChild(createShortcutElement(item));
    });

    // Sortable（ショートカット用）
    gridSortables.push(new Sortable(gridElement, {
        group: 'shared-shortcuts', // 【重要】これに共通の名前をつけることでカテゴリー間の移動が可能になる
        animation: 150,
        ghostClass: 'sortable-ghost',
        // 他のカテゴリーにドロップされた時も保存を走らせる
        onEnd: async () => { await syncOrder(); }
    }));

    return catElement;
}

function createIconElement(item) {
    if (typeof item.icon === 'string' && ICON_SRC_PATTERN.test(item.icon)) {
        const img = document.createElement('img');
        img.src = item.icon;
        img.className = 'icon-img';
        return img;
    }
    const placeholder = document.createElement('div');
    placeholder.className = 'icon-placeholder';
    const initial = document.createElement('span');
    // Array.from: 絵文字などのサロゲートペアを半分に割らない
    initial.textContent = (typeof item.name === 'string' && item.name.length > 0) ? Array.from(item.name)[0] : '';
    placeholder.appendChild(initial);
    return placeholder;
}

function createShortcutElement(item) {
    const itemElement = document.createElement('div');
    itemElement.className = 'shortcut-item';
    itemElement.setAttribute('data-id', item.id);

    const controls = document.createElement('div');
    controls.className = 'item-controls';

    const editBtn = document.createElement('span');
    editBtn.className = 'edit-btn';
    editBtn.title = i18n.prompt_new_name;
    editBtn.textContent = '✎';
    editBtn.addEventListener('click', (event) => renameShortcut(event, item.id, item.name));

    const deleteBtn = document.createElement('span');
    deleteBtn.className = 'delete-btn';
    deleteBtn.title = i18n.delete;
    deleteBtn.textContent = '✕';
    deleteBtn.addEventListener('click', (event) => removeShortcut(event, item.id));

    controls.append(editBtn, deleteBtn);

    const iconContainer = document.createElement('div');
    iconContainer.className = 'icon-container';
    iconContainer.title = item.name;
    iconContainer.appendChild(createIconElement(item));

    const label = document.createElement('span');
    label.textContent = item.name;

    itemElement.append(controls, iconContainer, label);

    itemElement.addEventListener('click', () => launchShortcut(item.id));
    return itemElement;
}

// 起動。クリックから約1秒は、どのカードのクリックも無視する（二重起動対策）
async function launchShortcut(id) {
    const now = Date.now();
    if (now < launchLockedUntil) return;
    launchLockedUntil = now + LAUNCH_COOLDOWN_MS;
    const success = await pywebview.api.launch_executable(id);
    if (!success) alert(i18n.error_launch);
}

// --- テーマ -------------------------------------------------------------------

/**
 * テーマ CSS と body のクラスを適用する。
 * 一覧（get_themes）に無い値は既定のテーマにする。
 */
function applyTheme(themeName) {
    const theme = normalizeTheme(themeName);

    const themeLink = document.getElementById('theme-link');
    if (themeLink) themeLink.href = `themes/${theme}.css`;

    // style.css の「.valorant .theme-select」等が body のテーマクラスに依存している。
    // 全上書きはせず、テーマのクラスだけを差し替える。
    const body = document.body;
    Array.from(body.classList)
        .filter(cls => cls !== theme && (availableThemes.includes(cls) || cls === DEFAULT_THEME))
        .forEach(cls => body.classList.remove(cls));
    body.classList.add(theme);

    // セレクトボックスの状態も合わせる
    const select = document.getElementById('theme-select');
    if (select) select.value = theme;
}

async function changeTheme(themeName) {
    const theme = normalizeTheme(themeName);
    // 1. CSS と body のクラスを差し替え
    applyTheme(theme);
    // 2. Python側の設定を更新（ConfigManager経由）
    if (!(await pywebview.api.update_setting("theme", theme))) await reportSaveFailure();
}

async function initThemeSelector() {
    const themeSelect = document.getElementById('theme-select');
    if (!themeSelect) return;

    // Pythonからテーマ名のリストを取得
    const themes = await pywebview.api.get_themes();
    availableThemes = Array.isArray(themes) ? themes.filter(t => typeof t === 'string') : [];

    // セレクトボックスを一旦クリアして作り直す
    themeSelect.replaceChildren();
    availableThemes.forEach(theme => {
        const option = document.createElement('option');
        option.value = theme;
        // ファイル名を綺麗に表示（例: hydrangea -> Hydrangea）
        option.textContent = theme.charAt(0).toUpperCase() + theme.slice(1);
        themeSelect.appendChild(option);
    });
}

// --- カテゴリー・ショートカット操作 -------------------------------------------

// カテゴリー追加
async function addCategory() {
    const name = prompt(i18n.prompt_category_name);
    if (name) {
        if (!(await pywebview.api.add_category(name))) await reportSaveFailure();
        renderApp(); // 再描画
    }
}

// ショートカット追加
async function addShortcut(categoryId) {
    const path = await pywebview.api.select_file();
    if (path) {
        const filename = path.split('\\').pop().split('/').pop().replace(/\.[^/.]+$/, "");
        // 翻訳ラベルを使用
        const name = prompt(i18n.prompt_confirm_app_name, filename);

        if (name) {
            const result = await pywebview.api.add_shortcut(categoryId, name, path);
            if (result && result.ok === false) alert(addShortcutErrorMessage(result));
            renderApp();
        }
    }
}

// add_shortcut のエラーコードを表示用の文に変える（alert で表示する。innerHTML には入れない）
function addShortcutErrorMessage(result) {
    const code = String(result.error || "");
    return i18n["error_" + code] || i18n.error_add_shortcut || code;
}

// ドロップされたファイルを追加する（Python 側の drop ハンドラーから呼ばれる）。
// files: [{name, path}]。path は Python 側でネイティブの記録と照合済みで、
// add_shortcut でも改めて検証される。
async function onFilesDropped(files) {
    const target = pendingDrop;
    pendingDrop = null;
    if (!target || Date.now() - target.at > DROP_TARGET_TTL_MS) return;
    if (!Array.isArray(files) || files.length === 0) return;

    const messages = [];
    for (const file of files) {
        if (!file || typeof file.path !== 'string' || typeof file.name !== 'string') continue;
        const result = await pywebview.api.add_shortcut(target.categoryId, file.name, file.path);
        if (result && result.ok === false) {
            const message = addShortcutErrorMessage(result);
            if (!messages.includes(message)) messages.push(message);
        }
    }
    if (messages.length) alert(messages.join('\n'));
    renderApp();
}
window.paletteLaunchOnDrop = onFilesDropped;

// ショートカット削除
async function removeShortcut(event, id) {
    event.stopPropagation();
    if (confirm(i18n.confirm_delete_shortcut)) {
        if (!(await pywebview.api.delete_shortcut(id))) await reportSaveFailure();
        renderApp();
    }
}

// ショートカット名変更
async function renameShortcut(event, id, currentName) {
    event.stopPropagation();
    const newName = prompt(i18n.prompt_new_name, currentName);
    if (newName && newName !== currentName) {
        if (!(await pywebview.api.edit_shortcut(id, newName))) await reportSaveFailure();
        renderApp();
    }
}

// カテゴリー削除
async function removeCategory(id) {
    if (confirm(i18n.confirm_delete_category)) {
        if (!(await pywebview.api.delete_category(id))) await reportSaveFailure();
        renderApp();
    }
}

// カテゴリー名の編集
async function renameCategory(id, currentName) {
    const newName = prompt(i18n.prompt_edit_category, currentName);
    if (newName && newName !== currentName) {
        if (!(await pywebview.api.edit_category(id, newName))) await reportSaveFailure();
        renderApp(); // 再描画
    }
}

// --- 順番をPythonに送る関数 ---
async function syncOrder() {
    const categoriesOrder = [];
    const sections = document.querySelectorAll('.category-section');

    sections.forEach(section => {
        const grid = section.querySelector('.shortcut-grid');
        const catId = grid.id.replace('grid-', '');

        // そのカテゴリー内のショートカットIDを順番に取得（itemElement の data-id）
        const shortcutIds = Array.from(grid.children).map(item => item.getAttribute('data-id'));

        categoriesOrder.push({
            id: catId,
            shortcuts: shortcutIds
        });
    });

    if (!(await pywebview.api.save_order(categoriesOrder))) {
        await reportSaveFailure();
        renderApp(); // 保存されていない並び順を、保存済みの状態に戻す
    }
}

// --- 言語 ---------------------------------------------------------------------

async function loadLanguage(langCode) {
    // 許可リスト外の値は fetch のパスに使わない
    const code = normalizeLanguage(langCode);
    try {
        // langフォルダからJSONを読み込む
        const response = await fetch(`lang/${code}.json`);
        i18n = await response.json();
        applyLabels();
    } catch (e) {
        console.error("Language file not found, falling back to English.");
        // 失敗した場合は英語をロード
        const response = await fetch(`lang/en.json`);
        i18n = await response.json();
        applyLabels();
    }
}

function applyLabels() {
    // 既存の翻訳適用
    document.title = i18n.app_title;
    const h1 = document.querySelector('h1');
    if (h1) h1.textContent = i18n.app_title;

    const addCatBtn = document.querySelector('.add-cat-btn');
    if (addCatBtn) addCatBtn.textContent = i18n.add_category;

    // カードサイズの選択肢を翻訳
    const sizeSelect = document.getElementById('card-size-select');
    if (sizeSelect) {
        sizeSelect.options[0].textContent = i18n.size_small || "Small";
        sizeSelect.options[1].textContent = i18n.size_medium || "Medium";
    }
}

/**
 * 言語を切り替えて保存する
 */
async function changeLanguage(langCode) {
    const code = normalizeLanguage(langCode);
    // 1. JSONファイルをロードしてラベルを書き換え
    await loadLanguage(code);

    // 2. Python側の settings.json を更新
    if (!(await pywebview.api.update_setting("language", code))) await reportSaveFailure();

    // 3. UI全体の再描画（カテゴリー内のボタンなども翻訳するため）
    renderApp();
}

// --- 設定 ---------------------------------------------------------------------

// カードサイズを反映する
async function loadAndApplySettings() {
    const fullData = await pywebview.api.get_config();
    const settings = fullData.config;

    // 「大」など許可外の値が設定に残っていたら「標準」に変換
    // （以前は const への再代入で例外になっていた）
    const currentSize = normalizeCardSize(settings.card_size);

    const container = document.getElementById('app-container');
    if (container) applyCardSizeClass(container, currentSize);

    // ドロップダウンの選択状態を合わせる
    const sizeSelect = document.getElementById('card-size-select');
    if (sizeSelect) sizeSelect.value = currentSize;
}

// --- 起動 ---------------------------------------------------------------------

bindStaticHandlers();

if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.get_config === 'function') {
    init();
} else {
    window.addEventListener('pywebviewready', init, { once: true });
}

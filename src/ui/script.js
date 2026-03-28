// 1. pywebviewの準備ができるまで待つ
window.addEventListener('pywebviewready', () => {
    console.log("Pythonとの通信準備完了");
    renderApp();
});

async function renderApp() {
    // テーマを取得
    await initThemeSelector();
    const container = document.getElementById('app-container');

    // 1. Pythonから最新のデータを取得
    const fullData = await pywebview.api.get_config();

    // 2. データを分解
    const categories = fullData.categories;
    // テーマ切り替えで使用
    const appConfig = fullData.config;

    const currentSize = appConfig.card_size || 'medium';
    container.classList.remove('size-small', 'size-medium', 'size-large');
    container.classList.add(`size-${currentSize}`);

    // 言語をロード（設定されている言語、なければ 'ja'）
    await loadLanguage(appConfig.language || 'ja');

    // セレクトボックスの値を現在の設定に合わせる
    document.getElementById('lang-select').value = appConfig.language || 'ja';

    container.innerHTML = '';

    // config.categories ではなく categories を使用
    categories.forEach(category => {
        const catElement = document.createElement('section');
        catElement.className = 'category-section';

        catElement.innerHTML = `
            <div class="category-header">
            <h2 class="category-title" 
                onclick="renameCategory('${category.id}', '${category.name}')" 
                style="cursor: pointer;" 
                title="${i18n.prompt_edit_category}">
                ${category.name}
            </h2>
            <div class="category-actions">
                <button onclick="addShortcut('${category.id}')" class="action-btn">${i18n.add_app}</button>
                <button onclick="removeCategory('${category.id}')" class="action-btn delete-cat">${i18n.delete}</button>
            </div>
        </div>
        <div class="shortcut-grid" id="grid-${category.id}"></div>
        `;
        container.appendChild(catElement);

        const gridElement = document.getElementById(`grid-${category.id}`);

        // --- ドラッグ＆ドロップイベント ---
        gridElement.addEventListener('dragover', (e) => { e.preventDefault(); gridElement.classList.add('drag-over'); });
        gridElement.addEventListener('dragleave', () => { gridElement.classList.remove('drag-over'); });
        gridElement.addEventListener('drop', async (e) => {
            e.preventDefault();
            gridElement.classList.remove('drag-over');
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                for (let file of files) {
                    const path = file.path || "";
                    const name = file.name.replace(/\.[^/.]+$/, "");
                    if (path) await pywebview.api.add_shortcut(category.id, name, path);
                }
                renderApp();
            }
        });

        // --- ショートカットの表示処理 ---
        category.shortcuts.forEach(item => {
            const itemElement = document.createElement('div');
            itemElement.className = 'shortcut-item';
            itemElement.setAttribute('data-id', item.id);

            const iconHtml = item.icon && item.icon.startsWith('data:image')
                ? `<img src="${item.icon}" class="icon-img">`
                : `<div class="icon-placeholder"><span>${item.name[0]}</span></div>`;

            itemElement.innerHTML = `
                <div class="item-controls">
                    <span class="edit-btn" onclick="renameShortcut(event, '${item.id}', '${item.name}')" title="${i18n.prompt_new_name}">✎</span>
                    <span class="delete-btn" onclick="removeShortcut(event, '${item.id}')" title="${i18n.delete}">✕</span>
                </div>
                <div class="icon-container" title="${item.name}">${iconHtml}</div>
                <span>${item.name}</span>
            `;

            itemElement.onclick = async () => {
                const success = await pywebview.api.launch_executable(item.id);
                if (!success) alert("アプリの起動に失敗しました。");
            };
            gridElement.appendChild(itemElement);
        });

        // Sortable（ショートカット用）
        new Sortable(gridElement, {
            group: 'shared-shortcuts', // 【重要】これに共通の名前をつけることでカテゴリー間の移動が可能になる
            animation: 150,
            ghostClass: 'sortable-ghost',
            // 他のカテゴリーにドロップされた時も保存を走らせる
            onEnd: async () => { await syncOrder(); }
        });
    });

    // Sortable（カテゴリー用）
    new Sortable(container, {
        animation: 150,
        handle: '.category-header',
        onEnd: async () => { await syncOrder(); }
    });

    // 【おまけ】テーマの適用
    applyTheme(appConfig.theme);
}

// テーマを反映させる関数も用意しておきましょう
function applyTheme(themeName) {
    const themeLink = document.getElementById('theme-link');
    if (themeLink) {
        themeLink.href = `themes/${themeName}.css`;
    }
}

// 3. カテゴリー追加
async function addCategory() {
    const name = prompt(i18n.prompt_category_name);
    if (name) {
        await pywebview.api.add_category(name);
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
            await pywebview.api.add_shortcut(categoryId, name, path);
            renderApp();
        }
    }
}

// ショートカット削除
async function removeShortcut(event, id) {
    event.stopPropagation();
    if (confirm(i18n.confirm_delete_shortcut)) {
        await pywebview.api.delete_shortcut(id);
        renderApp();
    }
}

// ショートカット名変更
async function renameShortcut(event, id, currentName) {
    event.stopPropagation();
    const newName = prompt(i18n.prompt_new_name, currentName);
    if (newName && newName !== currentName) {
        await pywebview.api.edit_shortcut(id, newName); // update_shortcut に名称を合わせる
        renderApp();
    }
}

// カテゴリー削除
async function removeCategory(id) {
    if (confirm(i18n.confirm_delete_category)) {
        await pywebview.api.delete_category(id);
        renderApp();
    }
}

// カテゴリー名の編集
async function renameCategory(id, currentName) {
    const newName = prompt(i18n.prompt_edit_category, currentName);
    if (newName && newName !== currentName) {
        await pywebview.api.edit_category(id, newName);
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

        // そのカテゴリー内のショートカットIDを順番に取得
        const shortcutIds = Array.from(grid.children).map(item => {
            // item-controlsなどからではなく、IDを保持している要素から取得
            // 修正ポイント：後述のitemElementにdata-idを持たせます
            return item.getAttribute('data-id');
        });

        categoriesOrder.push({
            id: catId,
            shortcuts: shortcutIds
        });
    });

    await pywebview.api.save_order(categoriesOrder);
}

async function changeTheme(themeName) {
    // 1. CSSファイルを差し替え
    const themeLink = document.getElementById('theme-link');
    themeLink.href = `themes/${themeName}.css`;

    // 2. Python側の設定を更新（ConfigManager経由）
    await pywebview.api.update_setting("theme", themeName);
}

// 既存の renderApp の最後にも applyTheme を追加してください
function applyTheme(themeName) {
    const themeLink = document.getElementById('theme-link');
    themeLink.href = `themes/${themeName}.css`;

    // セレクトボックスの状態も合わせる
    const select = document.getElementById('theme-select');
    if (select) select.value = themeName;
}

async function initThemeSelector() {
    const themeSelect = document.getElementById('theme-select');
    if (!themeSelect) return;

    // Pythonからテーマ名のリストを取得
    const themes = await pywebview.api.get_themes();

    // セレクトボックスを一旦クリアして作り直す
    themeSelect.innerHTML = '';
    themes.forEach(theme => {
        const option = document.createElement('option');
        option.value = theme;
        // ファイル名を綺麗に表示（例: hydrangea -> Hydrangea）
        option.textContent = theme.charAt(0).toUpperCase() + theme.slice(1);
        themeSelect.appendChild(option);
    });
}

let i18n = {}; // 翻訳データを保持する変数

async function loadLanguage(langCode) {
    try {
        // langフォルダからJSONを読み込む
        const response = await fetch(`lang/${langCode}.json`);
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

    // --- 追加：カードサイズの選択肢を翻訳 ---
    const sizeSelect = document.getElementById('card-size-select');
    if (sizeSelect) {
        // 各オプションのテキストを i18n データから取得
        sizeSelect.options[0].textContent = i18n.size_small || "Small";
        sizeSelect.options[1].textContent = i18n.size_medium || "Medium";
    }
}


/**
 * 言語を切り替えて保存する
 */
async function changeLanguage(langCode) {
    // 1. JSONファイルをロードしてラベルを書き換え
    await loadLanguage(langCode);

    // 2. Python側の settings.json を更新
    await pywebview.api.update_setting("language", langCode);

    // 3. UI全体の再描画（カテゴリー内のボタンなども翻訳するため）
    renderApp();
}

// 設定を反映する関数
async function applySettings() {
    const settings = await pywebview.api.get_settings();

    // 1. テーマの反映（既存）
    document.body.className = settings.theme;

    // 2. カードサイズの反映
    // コンテナ要素に size-small, size-medium, size-large のいずれかを付与
    const container = document.getElementById('shortcut-list');
    container.classList.remove('size-small', 'size-medium', 'size-large');
    container.classList.add(`size-${settings.card_size || 'medium'}`);
}


// 設定を反映するメイン関数
async function loadAndApplySettings() {
    // get_settings ではなく get_config を使用（既存のAPIに合わせる）
    const fullData = await pywebview.api.get_config();
    const settings = fullData.config; // Python側の戻り値に合わせて config を参照

    // 1. テーマの反映
    document.body.className = settings.theme;

    // 2. カードサイズの反映（ターゲットを app-container に変更）
    const container = document.getElementById('app-container');
    const currentSize = settings.card_size || 'medium';
    // 「大」が設定に残っていたら「標準」に変換
    if (currentSize === 'large') currentSize = 'medium';

    if (container) {
        container.classList.remove('size-small', 'size-medium', 'size-large');
        container.classList.add(`size-${currentSize}`);
    }

    // 3. ドロップダウンの選択状態を合わせる
    const sizeSelect = document.getElementById('card-size-select');
    if (sizeSelect) {
        sizeSelect.value = currentSize;
    }
}

// ドロップダウンのイベントリスナーも上記関数を呼ぶように修正
document.getElementById('card-size-select').addEventListener('change', async (event) => {
    const newSize = event.target.value;
    await pywebview.api.update_setting('card_size', newSize);
    await loadAndApplySettings(); // 修正後の関数を呼ぶ
});

// 初期化時に実行
window.addEventListener('pywebviewready', () => {
    loadAndApplySettings();
});
# Gmail API連携設定
GMAIL_PROVIDER = "google"
GMAIL_API_BASE_URL = "https://gmail.googleapis.com/gmail/v1/users/me"

# メール一覧取得(ID)時の1ページあたりの最大件数(Gmail APIの上限)
GMAIL_LIST_MAX_RESULTS = 500

# メールID一覧を全件取得する際にたどる最大ページ数(暴走防止の安全上限)
# GMAIL_LIST_MAX_RESULTS * GMAIL_LIST_MAX_PAGES 件までを取得対象とする
GMAIL_LIST_MAX_PAGES = 20

# メール一覧取得時に取得するヘッダー
GMAIL_LIST_METADATA_HEADERS = ["Subject", "From"]

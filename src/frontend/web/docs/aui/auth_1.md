結論としては、この条件なら **「内蔵ユーザ管理 + ID/パスワードログイン + サーバ側セッション Cookie」** が最適です。OAuth/OIDC、SAML、メール認証、外部IdP前提の仕組みは、この文脈では過剰で、低ICTスキルの現場では初期設定とトラブル対応が重くなります。

社内ネット限定・HTTP許容・installer/Docker配布なら、まずは次の構成が一番扱いやすいです。

```text
ブラウザ
  ↓
ログイン画面
  ↓ ID / パスワード
Webアプリ
  ↓
ユーザDBで検証
  ↓
サーバ側セッション作成
  ↓
HttpOnly Cookie を返す
```

Cookieにはユーザ情報や権限を直接入れず、**ランダムな session_id だけ**を入れます。サーバ側で `session_id -> user_id / role / expires_at` を保持します。OWASPもセッションIDの保管・管理を重要な防御点として扱っており、Cookieには少なくとも `HttpOnly` や `SameSite` を使うのが基本です。HTTP運用では `Secure` Cookie は使えないため、将来HTTPS化できる構成にしておくのがよいです。([OWASP Cheat Sheet Series][1])

パスワードは平文保存せず、**Argon2id**、難しければ **bcrypt** でハッシュ化して保存します。OWASPはパスワード保存では専用の安全な方式を使うべきとし、NISTもパスワードはソルト付きで、オフライン攻撃に耐える一方向KDFで保存することを求めています。([OWASP Cheat Sheet Series][2])

実装方針としては、これがよいです。

```text
初回起動
  - ユーザがまだ存在しない
  - installer / Docker 起動ログ / 初期画面に one-time setup code を表示
  - 管理者がブラウザで初期管理者を作成
  - 初期設定完了フラグを保存
  - 以後、初期管理者作成画面は無効化

通常利用
  - ユーザは ID / パスワードでログイン
  - 管理者がユーザ追加・無効化・パスワードリセット
  - role は admin / user 程度から開始
```

避けたほうがよいのは、**Basic認証、JWTだけの認証、共有パスワード、初期固定ID/固定パスワード、メールリンク認証**です。Basic認証はログアウトやユーザ管理が弱く、JWTは一見便利ですが、低ICTスキル向けのオンプレWebアプリでは失効・ローテーション・保管の設計が面倒です。共有パスワードは監査も権限制御もできません。メール認証は社内ネット・インターネット非接続構成と相性が悪いです。

より現実的な最適案は、**標準は内蔵認証、オプションでAD/LDAP連携**です。

```text
標準モード:
  内蔵ユーザDB + パスワード + セッションCookie

企業オプション:
  Active Directory / LDAP 連携
  ただし初期導入では必須にしない
```

製造業の現場だと、社内にActive Directoryがある会社も多いですが、現場部門だけで導入する場合、AD連携の設定情報を集めるだけで止まることがあります。なので、最初からAD必須にせず、**「まずローカル認証で動く」「必要な会社だけAD/LDAPに切り替えられる」**が一番導入しやすいです。

実装イメージはこのくらいで十分です。

```text
users
  id
  username
  display_name
  password_hash
  role
  is_active
  created_at
  updated_at

sessions
  id
  user_id
  expires_at
  created_at
  last_seen_at
  user_agent
  ip_address
```

Cookie設定はHTTP前提なら次のような考え方です。

```text
session_id=<random>
HttpOnly
SameSite=Lax or Strict
Path=/
Max-Age=8h〜24h
```

`Secure` はHTTPでは付けられません。将来HTTPSにできる場合は `Secure` を有効にします。HTTPを許容する場合でも、パスワードとセッションCookieはネットワーク上を平文で流れるため、**社内ネット限定でも「同一LAN上の盗聴には弱い」**という注意は残ります。ここは仕様書や管理者向け説明に明記したほうがよいです。

初期セットアップで一番事故りにくいのは、固定初期パスワードではなく、**初回起動時に一度だけ使える setup code を生成する方式**です。

```text
Docker起動ログ:
  Setup code: 834921

ブラウザ:
  http://server-ip:port/setup
  setup code を入力
  管理者IDとパスワードを作成
```

こうすると、`admin/admin` のような危険な初期値を避けられます。初期セットアップ完了後は `/setup` を無効化します。

最終的な推奨はこれです。

```text
第1候補:
  内蔵ユーザ管理 + ID/パスワード + サーバ側セッションCookie

追加推奨:
  初回のみ one-time setup code
  管理者画面でユーザ作成・無効化・パスワードリセット
  Argon2id / bcrypt によるパスワード保存
  HttpOnly + SameSite Cookie
  role は admin / user から開始

将来オプション:
  AD / LDAP 連携
  HTTPS対応
  監査ログ
  端末・IP制限
```

この条件では、OAuthよりも、**「昔ながらのログイン画面を正しく作る」**のが一番強いです。認証方式自体を高度にするより、初期導入・ユーザ追加・パスワード忘れ・権限管理・ログアウト・セッション失効が現場で迷わず使えることを優先したほうがよいです。

[1]: https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html?utm_source=chatgpt.com "Session Management Cheat Sheet"
[2]: https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html?utm_source=chatgpt.com "Password Storage - OWASP Cheat Sheet Series"


-----


はい、**複数の認証方式を許す設計は十分可能**です。むしろ最初からその前提で作っておくのがよいです。ただし重要なのは、**認証方式を複数にしても、アプリ内のユーザ・権限・セッション管理は1つに統一する**ことです。

設計の芯はこうです。

```text id="v6qk9e"
ログイン方法:
  - local: 独自ID/パスワード
  - ldap: 社内AD/LDAP
  - oidc: Keycloakなど
  - header: リバースプロキシ認証など

アプリ内:
  - users テーブルは共通
  - sessions テーブルも共通
  - role / 権限も共通
```

つまり、ログイン入口はいくつあっても、ログイン成功後は全部同じ `users.id` に紐づけます。

```text id="rn0xw7"
Local認証でログイン
  ↓
users.id = 10 として扱う
  ↓
session_id 発行

LDAP認証でログイン
  ↓
users.id = 10 として扱う
  ↓
session_id 発行

OIDC認証でログイン
  ↓
users.id = 10 として扱う
  ↓
session_id 発行
```

このようにすると、アプリ本体は「この人がlocalでログインしたのか、LDAPでログインしたのか」をあまり意識しなくて済みます。アプリは基本的に `session_id -> user_id -> role` だけ見ればよくなります。

DB設計は、`users` と `auth_identities` を分けるのがよいです。

```text id="7lu2b0"
users
  id
  display_name
  email
  role
  is_active
  created_at

auth_identities
  id
  user_id
  provider
  provider_subject
  username
  password_hash
  created_at

sessions
  id
  user_id
  expires_at
  created_at
```

`users` はアプリ内のユーザ本体です。`auth_identities` はログイン手段です。

たとえば同じ山田さんに対して、こういう紐づけができます。

```text id="dbemyr"
users
  id: 10
  display_name: 山田太郎
  role: admin

auth_identities
  user_id: 10
  provider: local
  username: yamada

auth_identities
  user_id: 10
  provider: ldap
  provider_subject: CN=yamada,OU=Users,DC=company,DC=local
```

この設計にしておくと、最初は独自ID/パスワードだけで始めて、あとからLDAPやKeycloakを追加できます。

ただし、今回の利用者像を考えると、最初からログイン画面に複数方式を並べるのはおすすめしません。低ICTスキルのユーザには混乱しやすいです。

おすすめはこれです。

```text id="hzutxk"
初期状態:
  ローカル認証のみ有効

管理者設定:
  LDAP / OIDC を有効化できる

ログイン画面:
  有効な認証方式だけ表示する
```

たとえばLDAPが未設定なら、ログイン画面には普通のID/パスワードだけ出します。LDAPを設定した会社では「社内アカウントでログイン」を出します。

実装上は、認証方式ごとに `AuthProvider` を差し替える形にするときれいです。

```text id="7rq4u7"
AuthProvider
  - LocalPasswordAuthProvider
  - LdapAuthProvider
  - OidcAuthProvider
  - HeaderAuthProvider
```

各Providerの責務は、ログイン情報を受け取って「アプリ内の user_id を返す」ことです。

```text id="nozver"
login(credentials)
  ↓
provider.authenticate(credentials)
  ↓
user_id を返す
  ↓
session を作る
```

疑似コードにするとこうです。

```python
class AuthResult:
    def __init__(self, user_id: str):
        self.user_id = user_id


class AuthProvider:
    name: str

    async def authenticate(self, credentials) -> AuthResult:
        raise NotImplementedError


class LocalPasswordAuthProvider(AuthProvider):
    name = "local"

    async def authenticate(self, credentials) -> AuthResult:
        user = find_user_by_username(credentials.username)
        verify_password(credentials.password, user.password_hash)
        return AuthResult(user_id=user.id)


class LdapAuthProvider(AuthProvider):
    name = "ldap"

    async def authenticate(self, credentials) -> AuthResult:
        ldap_user = ldap_bind(credentials.username, credentials.password)
        user = find_or_create_user_from_ldap(ldap_user)
        return AuthResult(user_id=user.id)
```

セッション作成はProvider側ではなく、共通処理にします。

```python
async def login(provider_name: str, credentials):
    provider = auth_registry.get(provider_name)

    auth_result = await provider.authenticate(credentials)

    session = create_session(user_id=auth_result.user_id)

    return set_session_cookie(session.id)
```

この分離がかなり重要です。Providerが増えても、セッション・権限・監査ログの仕組みは増やさなくてよくなります。

今回の文脈での最適な段階設計はこうです。

```text id="nhmxbn"
Phase 1:
  ローカルID/パスワード認証
  サーバ側セッション
  admin / user 権限
  初回setup code

Phase 2:
  LDAP / Active Directory 認証を追加
  ローカル管理者アカウントは緊急用に残す

Phase 3:
  OIDC / Keycloak 対応
  大きめの会社向けオプションにする
```

注意点として、**認証方式ごとに別ユーザを作ってしまう設計**は避けたほうがよいです。

```text id="p6gq3r"
NG:
  localの山田さん = user_id 10
  ldapの山田さん = user_id 25
  oidcの山田さん = user_id 31
```

これをやると、権限・履歴・成果物・監査ログが分裂します。正しくは、複数のログイン手段を1人のアプリユーザに紐づけます。

```text id="eizy71"
OK:
  users.id = 10
    ├ local: yamada
    ├ ldap: company\yamada
    └ oidc: keycloak-sub-xxxx
```

また、ローカル認証を完全に消すより、**緊急用のローカル管理者アカウントは残せる設計**のほうが現場では安全です。LDAPやKeycloak設定を間違えると誰もログインできなくなるためです。ただし、その緊急管理者は無効化可能にし、強いパスワードを要求したほうがよいです。

結論としては、最初から次の設計にしておくのがよいです。

```text id="aw3a97"
認証方式:
  plugin / provider として拡張可能にする

アプリ内ユーザ:
  users テーブルに統一する

ログイン手段:
  auth_identities テーブルで users に紐づける

ログイン後:
  どの認証方式でも共通の session_id を発行する

権限:
  認証方式ではなく users.role で判断する
```

なので、あなたの理解している **「独自user/pass + サーバ側セッション」** を土台にしつつ、将来のために **AuthProvider方式** にしておくのが一番よいです。最初の実装はローカル認証だけで十分ですが、DBと処理の境界だけ最初から分けておくと、LDAPやOIDCを後から足しても設計が崩れません。



-------


結論としては、**roleを含めても、構成はまだかなりシンプルにできます**。おすすめは、認証・認可を分けすぎず、まずは **「users.role による単純RBAC + sessions + 管理者用ユーザ管理API」** で作ることです。

最初の完成形はこれで十分です。

```text id="9e0s5t"
Auth v1.5:
  - 初回セットアップ
  - ログイン
  - ログアウト
  - 自分の情報取得
  - パスワード変更
  - 管理者によるユーザ作成
  - 管理者によるユーザ無効化
  - 管理者によるパスワードリセット
  - role による簡易認可
```

roleは、最初は **admin / user** の2つでよいです。複雑な権限テーブルや permission 一覧は、今は入れないほうがよいです。

```text id="n48gep"
admin:
  ユーザ管理ができる
  すべての通常機能を使える

user:
  通常機能を使える
  ユーザ管理はできない
```

DBはこのくらいで十分です。

```sql id="hhsx94"
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'user')),
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE audit_logs (
    id TEXT PRIMARY KEY,
    actor_user_id TEXT,
    action TEXT NOT NULL,
    target_user_id TEXT,
    detail TEXT,
    created_at TEXT NOT NULL
);
```

`audit_logs` は少し増えますが、入れたほうがよいです。ユーザ作成、無効化、パスワードリセットなどは後で「誰がやったか」を見たくなるためです。詳細な監査基盤ではなく、まずは1テーブルで十分です。

パスワードは平文保存ではなく、Argon2id または bcrypt で保存します。OWASPはパスワードを平文保存せず、Argon2id・bcrypt・PBKDF2 のような低速なパスワードハッシュを使うべきとしています。NISTも、パスワードはソルト付きで、オフライン攻撃に耐える方式で保存することを求めています。([OWASP Cheat Sheet Series][1])

APIはこれでよいです。

```text id="xp9xs3"
初期設定:
  POST /auth/setup

ログイン系:
  POST /auth/login
  POST /auth/logout
  GET  /auth/me
  POST /auth/change-password

管理者用:
  GET  /admin/users
  POST /admin/users
  PATCH /admin/users/{user_id}
  POST /admin/users/{user_id}/reset-password
  POST /admin/users/{user_id}/logout
```

`PATCH /admin/users/{user_id}` では、まずはこの3つだけ変更できればよいです。

```text id="souuie"
display_name
role
is_active
```

認可はシンプルに、FastAPIの dependency で分けます。

```text id="1xg7jl"
require_login:
  ログイン済みならOK

require_admin:
  ログイン済み、かつ user.role == 'admin' ならOK
```

実装イメージはこうです。

```python id="lkbhb0"
from fastapi import Depends, HTTPException, Request, status

SESSION_COOKIE_NAME = "session_id"


def require_login(request: Request) -> User:
    session_id = request.cookies.get(SESSION_COOKIE_NAME)

    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    user = find_user_by_session_id(session_id)

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    return user


def require_admin(user: User = Depends(require_login)) -> User:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin permission required",
        )

    return user
```

通常APIには `require_login` を付けます。

```python id="ocg4tx"
@app.get("/api/profile")
def get_profile(user: User = Depends(require_login)):
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
    }
```

管理者APIには `require_admin` を付けます。

```python id="hid1b1"
@app.post("/admin/users")
def create_user(
    req: CreateUserRequest,
    admin: User = Depends(require_admin),
):
    user = create_local_user(
        username=req.username,
        display_name=req.display_name,
        password=req.password,
        role=req.role,
    )

    write_audit_log(
        actor_user_id=admin.id,
        action="user.create",
        target_user_id=user.id,
    )

    return user
```

Cookieは、HTTP社内LAN前提ならこうです。

```python id="syh8be"
def set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        samesite="lax",
        secure=False,  # HTTPS化したら True
        max_age=60 * 60 * 24,
        path="/",
    )
```

セッションCookieには `HttpOnly` を付けて、JavaScriptから読めないようにするのが基本です。OWASPも `HttpOnly` はセッションIDの盗難対策として重要だと説明しています。また `SameSite` はクロスサイトリクエスト時のCookie送信を制御する属性です。([OWASP Cheat Sheet Series][2])

重要なのは、**Cookieには role を入れない**ことです。

```text id="zqgaym"
NG:
  Cookie に user_id / role / username を入れる

OK:
  Cookie には session_id だけ入れる
  role は毎回 users テーブルから見る
```

これなら、管理者があるユーザを `admin` から `user` に変更したとき、次のリクエストからすぐ反映できます。Cookieにroleを入れていると、role変更の反映や失効処理が面倒になります。

パスワード変更は、自分で変更する場合と、管理者がリセットする場合を分けます。

```text id="x4mxfa"
POST /auth/change-password:
  本人が old_password + new_password を入力
  old_password を検証
  new_password を hash 化して保存
  既存セッションを削除して再ログインさせてもよい

POST /admin/users/{user_id}/reset-password:
  管理者が仮パスワードを設定
  対象ユーザの既存セッションを削除
  次回ログイン時に変更させる
```

そのために、必要なら `must_change_password` を users に追加します。

```sql id="s66ipl"
ALTER TABLE users
ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0;
```

最初から入れるなら、usersはこうなります。

```sql id="oh1j2v"
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'user')),
    is_active INTEGER NOT NULL DEFAULT 1,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

ユーザ無効化の挙動は、これがよいです。

```text id="argxle"
管理者が is_active = 0 にする
  ↓
対象ユーザの sessions を全削除
  ↓
以後ログイン不可
  ↓
既存画面を開いていても次のAPIで401
```

ログアウトの挙動は、単にセッションを削除します。

```text id="1ilj9k"
POST /auth/logout
  - 現在の session_id を sessions から削除
  - Cookie を削除
```

管理者による強制ログアウトは、対象ユーザのセッションを全部消します。

```text id="18szpk"
POST /admin/users/{user_id}/logout
  - sessions where user_id = target_user_id を削除
```

初回セットアップは、usersが空のときだけ許可します。

```text id="qj6k79"
POST /auth/setup
  - users が空であることを確認
  - admin ユーザを作成
  - セッションを作成
  - Cookieをセット
```

低ICTスキル向けなら、最初の画面はこういう流れにすると分かりやすいです。

```text id="re48ix"
アプリ起動
  ↓
GET /auth/me
  ↓
401
  ↓
GET /auth/setup-status
  ↓
setup_required = true
  ↓
初期管理者作成画面を表示
```

`/auth/setup-status` はあると便利です。

```text id="sp3tpb"
GET /auth/setup-status

response:
{
  "setup_required": true
}
```

フロントエンドは、だいたいこの判定でよいです。

```text id="q97np3"
起動時:
  GET /auth/me

200:
  アプリ画面へ

401:
  GET /auth/setup-status

setup_required = true:
  初期管理者作成画面へ

setup_required = false:
  ログイン画面へ
```

全体構成はこれくらいが最もバランスがよいです。

```text id="q6f523"
auth/
  password.py
  session.py
  service.py
  dependencies.py
  routes.py

admin/
  user_routes.py

db/
  schema.sql
  repository.py
```

処理を分けるなら、この程度で十分です。

```text id="dqt0xj"
password.py:
  hash_password
  verify_password

session.py:
  create_session
  delete_session
  delete_user_sessions
  find_user_by_session

service.py:
  setup_admin
  login
  logout
  change_password

admin/user_routes.py:
  list_users
  create_user
  update_user
  reset_password
  force_logout
```

一番避けたいのは、最初からこうすることです。

```text id="l5bm1h"
避ける:
  - permission テーブルを作る
  - role_permissions を作る
  - resourceごとの細かい認可を作る
  - JWTでroleを持つ
  - 認証方式ごとに別セッションにする
```

今の段階では、`admin / user` の2ロールだけで十分です。後から必要になったら、`operator` や `viewer` を足せばよいです。

最終案はこれです。

```text id="z8pgp3"
シンプル構成:
  - users.role で admin / user
  - sessions テーブルでログイン状態
  - Cookie は session_id のみ
  - require_login / require_admin の2つだけ
  - 管理者APIでユーザ作成・無効化・role変更・パスワードリセット
  - audit_logs で最低限の操作履歴
```

この構成なら、かなりシンプルなまま、実運用に必要な機能まで入ります。最初に作るべき中核は、**users / sessions / audit_logs と require_login / require_admin** です。これができれば、認証・簡易認可・ユーザ管理は一通り成立します。

[1]: https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html?utm_source=chatgpt.com "Password Storage - OWASP Cheat Sheet Series"
[2]: https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html?utm_source=chatgpt.com "Session Management - OWASP Cheat Sheet Series"



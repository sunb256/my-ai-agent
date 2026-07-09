
結論として、**保存済みの `password_hash` を復号して確認するのではなく、入力されたパスワードを同じ方式で検証して「一致するか」をライブラリに判定させます**。

パスワードハッシュは、だいたいこういう文字列になります。

```text id="4y8j5i"
$argon2id$v=19$m=65536,t=3,p=4$ランダムsalt$計算結果
```

ここには、平文パスワードは入っていません。代わりに、次の情報が入っています。

```text id="hdt8zr"
ハッシュ方式:
  argon2id など

計算パラメータ:
  メモリ量、回数など

salt:
  ユーザごとに異なるランダム値

計算結果:
  パスワード + salt から作った結果
```

ログイン時の流れはこうです。

```text id="xmmuj1"
ユーザが username / password を入力
  ↓
username で users テーブルを検索
  ↓
保存済み password_hash を取得
  ↓
入力された password と password_hash を検証
  ↓
一致すればログイン成功
  ↓
sessions に session_id を作る
```

重要なのは、アプリ側でこうしないことです。

```text id="hqqkcg"
NG:
  保存済みハッシュを復号する
  入力パスワードを自前でSHA-256する
  saltを自分で雑に連結して比較する
```

正しくは、パスワードハッシュ用ライブラリの `verify` を使います。

```python id="telgsi"
from pwdlib import PasswordHash

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return password_hash.verify(password, hashed_password)
```

ユーザ作成時はこうです。

```python id="xnzbs7"
plain_password = "user-input-password"

hashed_password = hash_password(plain_password)

# users.password_hash に保存する
```

ログイン時はこうです。

```python id="c6j4w4"
user = find_user_by_username(username)

if user is None:
    raise LoginError("ユーザ名またはパスワードが違います")

if not verify_password(input_password, user.password_hash):
    raise LoginError("ユーザ名またはパスワードが違います")

# ここまで来たらパスワードは正しい
session = create_session(user_id=user.id)
```

たとえば、ユーザ作成時にこう保存されていたとします。

```text id="ksayvf"
username: yamada
password_hash: $argon2id$v=19$m=65536,t=3,p=4$abc...$xyz...
```

ログイン時に `password123` が入力されたら、ライブラリは保存済みハッシュの中から `argon2id`、パラメータ、salt を読み取り、入力パスワードで同じ計算をします。その計算結果が保存済みの結果と一致すれば、パスワードが合っていると判断します。

なので、アプリがやることはかなり単純です。

```text id="p3t50p"
登録時:
  password_hash = hash_password(password)

ログイン時:
  verify_password(input_password, user.password_hash)
```

FastAPIのログイン処理に組み込むと、こういう形です。

```python id="kvesmz"
@router.post("/login")
def login(req: LoginRequest, response: Response):
    user = user_repo.find_by_username(req.username)

    if user is None:
        raise HTTPException(
            status_code=401,
            detail="ユーザ名またはパスワードが違います",
        )

    if not verify_password(req.password, user.password_hash):
        raise HTTPException(
            status_code=401,
            detail="ユーザ名またはパスワードが違います",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=401,
            detail="ユーザ名またはパスワードが違います",
        )

    session_id = session_repo.create_session(user_id=user.id)

    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
        max_age=60 * 60 * 24,
    )

    return {
        "ok": True,
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "role": user.role,
        },
    }
```

細かいですが、エラーメッセージは **「ユーザが存在しません」** と **「パスワードが違います」** を分けないほうがよいです。攻撃者に「このユーザ名は存在する」と教えてしまうためです。

```text id="u1s9p5"
避ける:
  ユーザが存在しません
  パスワードが違います

推奨:
  ユーザ名またはパスワードが違います
```

まとめると、パスワード確認の本質はこれです。

```text id="jsau9d"
保存するもの:
  平文パスワードではなく password_hash

ログイン時に使うもの:
  入力パスワード + 保存済み password_hash

確認方法:
  verify_password(input_password, saved_password_hash)

成功したら:
  session_id を発行して Cookie に入れる
```

つまり、**パスワードを復元して比べるのではなく、入力されたパスワードが保存済みハッシュと整合するかを検証する**、という仕組みです。


------


はい、ざっくり言うと **「入力された password を、保存済み `password_hash` に含まれている条件で再計算して、結果が合うか比較する」** ということです。

ただし、単純にこうではありません。

```python
hash(input_password) == saved_password_hash
```

なぜなら、パスワードハッシュには通常 **salt** が入っているからです。salt はユーザごとに違うランダム値です。

たとえばDBにはこういう値が保存されています。

```text
$argon2id$v=19$m=65536,t=3,p=4$abc123salt$xyz789hash
```

この1つの文字列の中に、だいたい次の情報が入っています。

```text
argon2id        ← ハッシュ方式
m=65536,t=3...  ← 計算パラメータ
abc123salt      ← salt
xyz789hash      ← 計算結果
```

ログイン時は、ライブラリがこの保存済みハッシュを読み取って、

```text
入力された password
+
保存済み password_hash の中にある salt
+
保存済み password_hash の中にある計算パラメータ
```

を使って、もう一度同じ計算をします。その計算結果が `xyz789hash` と一致すれば、パスワードが正しいと判断します。

つまりイメージとしてはこうです。

```text
登録時:

password = "abc123"
salt = ランダム値

password_hash = hash("abc123" + salt)

DBに保存:
  password_hash
```

ログイン時:

```text
入力 password = "abc123"

DBから password_hash を取得
  ↓
password_hash の中から salt と計算条件を読む
  ↓
入力 password + salt で再計算
  ↓
保存済みの計算結果と一致するか確認
```

コード上は、自分で分解して比較する必要はありません。ライブラリの `verify()` に任せます。

```python
from pwdlib import PasswordHash

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return password_hash.verify(password, hashed_password)
```

登録時はこうです。

```python
hashed = hash_password("abc123")

# DBには hashed を保存する
```

ログイン時はこうです。

```python
ok = verify_password("abc123", user.password_hash)

if ok:
    print("パスワードは正しい")
else:
    print("パスワードが違う")
```

なので、あなたの理解を少し正確に言うと、

**入力された password をハッシュ化して比較する、でほぼ合っています。
ただし、そのハッシュ化には保存済み `password_hash` の中に入っている salt や計算条件を使うので、自前で単純に hash して比較するのではなく、`verify()` を使う。**

ということです。


# Spotplay

コマンドラインからSpotifyを操作し、指定したアーティストの曲、トラック、プレイリストを再生するためのツールです。

## 概要

Spotplayは、Spotifyの再生を手軽にコマンドラインから行うためのPythonスクリプトです。再生したいアーティスト名、トラックのURI、プレイリストのURIを引数として渡すことで、指定したデバイスで音楽を再生します。

内部的には、初回実行時に`SpotplayList`という名前の専用プレイリストをSpotifyアカウントに作成します。コマンドが実行されるたびに、このプレイリストはクリアされ、新しく指定された曲が追加されて再生が開始されます。

## 特徴

-   **シンプルな操作**: 初回認証後は、コマンド一つで再生を開始できます。
-   **柔軟な入力**: アーティスト名、トラックURI、プレイリストURIを自由に組み合わせて指定可能です。
-   **デバイス指定**: 再生するデバイスを名前で指定できます。指定しない場合はアクティブなデバイスが自動で選択されます。
-   **自動シャッフル**: 指定された曲はシャッフルされてプレイリストに追加されるため、毎回異なる順番で楽しめます。

## インストール

1.  リポジトリをクローンします。
    ```shell
    git clone https://github.com/matchy256/spotplay.git
    cd spotplay
    ```

2.  必要なライブラリをインストールします。
    ```shell
    pip install -r requirements.txt
    ```

## 事前準備

### 1. Spotify APIキーの取得

このツールを利用するには、Spotify for Developersから`Client ID`と`Client Secret`を取得する必要があります。

1.  [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/)にアクセスし、お持ちのSpotifyアカウントでログインします。
2.  **"Create app"** をクリックします。
3.  "App name"と"App description"を自由に入力し、規約に同意して **"Create"** をクリックします。
4.  作成したアプリのダッシュボードで、**"Client ID"** をコピーします。次に **"Show client secret"** をクリックして **"Client Secret"** もコピーします。
5.  **"Edit settings"** をクリックします。
6.  "Redirect URIs"の欄に、以下のURLを追加し、**"Save"** をクリックします。
    ```
    https://matchy256.github.io/spotplay/auth-redirect/
    ```

### 2. .envファイルの設定

プロジェクトのルートディレクトリ（`spotplay.py`と同じ場所）に`.env`という名前のファイルを作成し、取得した`Client ID`と`Client Secret`を以下のように記述します。

```env
SPOTIFY_CLIENT_ID="YOUR_SPOTIFY_CLIENT_ID"
SPOTIFY_CLIENT_SECRET="YOUR_SPOTIFY_CLIENT_SECRET"
```

## 使い方

### 初回認証

初めてコマンドを実行すると、ターミナルに認証用のURLが表示されます。

```shell
$ python spotplay.py -l
 以下のURLをブラウザで開き、認証コードを取得してください:
https://accounts.spotify.com/authorize?client_id=...
認証コードを入力してください:
```

1.  表示されたURLにブラウザでアクセスし、Spotifyにログインしてアクセスを許可します。
2.  承認後、リダイレクト先のページに 「Spotify 認証完了」と表示されるので、「コピー」ボタンをクリックします。
3.  コピーした認証コードを、ターミナルの `認可コードを入力してください:` の後に入力してEnterキーを押します。

認証が成功すると、認証情報がホームディレクトリ以下の `~/.config/spotplay/` に保存され、次回以降はこの手順は不要になります。

### 利用可能なデバイス一覧を表示

再生可能なデバイスの一覧を確認するには、`-l`または`--list-devices`オプションを使用します。

```shell
python spotplay.py -l
```
出力例:
```
利用可能なデバイス:
  - My MacBook Pro (アクティブ)
  - iPhone
  - Echo Dot
```

### Spotify URIとは？

Spotify URIは、Spotify上のトラック、アルバム、プレイリスト、アーティストなどを一意に識別するためのIDです。`spotify:track:xxxxxxxxxxxxxx` のような形式をしています。

**URIの取得方法:**

1.  SpotifyのデスクトップアプリまたはWebプレイヤーで、対象のトラックまたはプレイリストを探します。
2.  対象のアイテムの横にある「...」（その他）メニューをクリックします。
3.  「シェア」にカーソルを合わせます。
4.  **Optionキー（Mac）** または **Altキー（Windows）** を押すと、「Spotify URIをコピー」という選択肢が表示されるので、それをクリックします。

このURIをコピーして、コマンドの引数として利用できます。

### 曲を再生

アーティスト名、トラックURI、プレイリストURIを引数として指定します。複数指定も可能です。

-dまたは--deviceオプションで再生したいデバイス名を指定できます。指定しない場合は、現在アクティブなデバイスで再生されます。

**コマンド例:**

```shell
# アーティストの曲を再生
python spotplay.py "Norah Jones"

# 複数のアーティストの曲を再生
python spotplay.py "Miles Davis" "John Coltrane"

# トラックやプレイリストを指定して再生
python spotplay.py spotify:track:xxxxxxxxxxxxxx spotify:playlist:xxxxxxxxxxxxxx

# デバイスを指定して再生
python spotplay.py "Stevie Wonder" -d "Echo Dot"
```

## ⚠️ 注意事項

-   **Spotify Premiumアカウントが必要**: このツールの全ての機能（特にデバイスの選択と再生コントロール）を利用するには、Spotifyの有料プラン（Premium）に加入している必要があります。無料プランでは正常に動作しません。
-   **専用プレイリスト**: このツールは、初回実行時に `SpotplayList` という名前のプレイリストを自動で作成します。このプレイリストはツールの動作に必須ですので、手動で削除しないでください。
-   **非対応のプレイリスト**: "This is XXXX" や "Artist Radio" のような、Spotifyが動的に生成する一部のプレイリストは、API経由でのトラック取得が制限されている場合があります。これらのプレイリストを指定すると、曲が取得できずにエラーとなる可能性があります。
-   **動作がおかしい場合 (トラブルシューティング)**: もしツールの動作が不安定になったり、エラーが発生したりした場合は、以下の手順でリセットを試みてください。
    1.  Spotify上で `SpotplayList` という名前のプレイリストを削除します。
    2.  ターミナルで以下のコマンドを実行し、設定ファイルとトークンを削除します。
        ```shell
        rm -rf ~/.config/spotplay
        ```
    3.  再度、`python spotplay.py` を実行し、初回認証からやり直してください。

## ライセンス

このプロジェクトはMITライセンスです。詳細は[LICENSE](LICENSE)ファイルをご覧ください。

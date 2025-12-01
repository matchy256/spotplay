#!/usr/bin/env python3

import os
import json
import random
import time
import argparse
import requests
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv

# -----------------------------
# 設定
# -----------------------------
load_dotenv()
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = "https://matchy256.github.io/spotplay/auth-redirect/"
SCOPE = (
    "playlist-modify-public "
    "playlist-modify-private "
    "user-modify-playback-state "
    "user-read-playback-state"
)

# 設定ディレクトリやプレイリストID保存先など
CONFIG_DIR = os.path.expanduser("~/.config/spotplay")
PLAYLIST_FILE = os.path.join(CONFIG_DIR, "playlist_id.txt")
CACHE_FILE = os.path.join(CONFIG_DIR, ".cache")
FIXED_PLAYLIST_NAME = "SpotplayList"

os.makedirs(CONFIG_DIR, exist_ok=True)

# -----------------------------
# Spotify 認証・APIクライアント関連
# -----------------------------

def get_spotify_client():
    """
    ブラウザを開かず手動コピペ認証フローでSpotify APIクライアントを取得
    """
    sp_oauth = SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
        cache_path=CACHE_FILE,
        open_browser=False  # 自動ブラウザ起動無効
    )

    # キャッシュ済みトークンがあれば使用
    token_info = sp_oauth.get_cached_token()
    if not token_info:
        # 認証URLを表示してユーザーにコードを入力してもらう
        auth_url = sp_oauth.get_authorize_url()
        print("以下のURLをブラウザで開き、認証コードを取得してください:")
        print(auth_url)
        code = input("認証コードを入力してください: ").strip()
        token_info = sp_oauth.get_access_token(code)

    # タイムアウトとリトライを設定したrequestsセッションを作成
    session = requests.Session()
    retries = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)

    # Spotifyクライアントを生成
    sp = spotipy.Spotify(auth=token_info["access_token"], requests_session=session, requests_timeout=30)
    return sp

# -----------------------------
# デバイス関連
# -----------------------------

def get_active_device(sp):
    """
    アクティブな（現在再生中、もしくは再生可能な）デバイスのIDを取得する。
    アクティブなデバイスがなければ、利用可能なデバイスから選択する。
    """
    devices = sp.devices().get("devices", [])
    if not devices:
        raise RuntimeError("アクティブなSpotifyデバイスが見つかりません。")

    # アクティブなデバイスを優先
    for d in devices:
        if d.get("is_active") and not d.get("is_restricted"):
            return d["id"]

    # アクティブなものがなければ、再生制限のないデバイスを選択
    for d in devices:
        if not d.get("is_restricted"):
            return d["id"]

    raise RuntimeError("再生可能なデバイスが見つかりません。")

def handle_device_listing(sp):
    """利用可能なSpotifyデバイスを一覧表示する"""
    devices = sp.devices().get('devices', [])
    if not devices:
        print("利用可能なデバイスが見つかりません。")
        return
    print("利用可能なデバイス:")
    for device in devices:
        active_str = " (アクティブ)" if device.get('is_active') else ""
        print(f"  - {device['name']}{active_str}")

def get_target_device_id(sp, device_name):
    """
    指定されたデバイス名に一致するIDを返す。
    見つからなければ、アクティブなデバイスのIDを返す。
    """
    if device_name:
        devices = sp.devices().get('devices', [])
        for d in devices:
            if d['name'].lower() == device_name.lower():
                print(f"{d['name']} を再生デバイスに設定しました。")
                return d['id']
        print(f"警告: デバイス '{device_name}' が見つかりません。アクティブなデバイスで再生します。")
    return get_active_device(sp)

# -----------------------------
# プレイリスト関連
# -----------------------------

def get_or_create_playlist(sp, user_id, name):
    """
    ~/.config/spotplay/playlist_id.txt からIDを読み込む。
    なければ固定名のプレイリストを探すか、新規作成してIDを保存する。
    """
    if os.path.exists(PLAYLIST_FILE):
        with open(PLAYLIST_FILE) as f:
            return f.read().strip()

    # 既存のプレイリストを検索
    playlists = sp.current_user_playlists(limit=50).get("items", [])
    for pl in playlists:
        if pl["name"] == name:
            playlist_id = pl["id"]
            with open(PLAYLIST_FILE, "w") as f:
                f.write(playlist_id)
            return playlist_id

    # プレイリストを新規作成
    pl = sp.user_playlist_create(user_id, name, public=False)
    playlist_id = pl["id"]
    with open(PLAYLIST_FILE, "w") as f:
        f.write(playlist_id)
    return playlist_id

def clear_playlist(sp, playlist_id):
    """
    プレイリスト内の全トラックを削除する。
    APIの100件制限を考慮し、分割してリトライ処理も行う。
    """
    while True:
        items = sp.playlist_items(playlist_id, fields="items.track.id,total", limit=100).get("items", [])
        track_ids = [t["track"]["id"] for t in items if t.get("track")]
        if not track_ids:
            break

        # 100件ずつ削除
        for i in range(0, len(track_ids), 100):
            chunk = track_ids[i:i+100]
            for attempt in range(5):
                try:
                    sp.playlist_remove_all_occurrences_of_items(playlist_id, chunk)
                    time.sleep(0.5)
                    break
                except requests.exceptions.ReadTimeout:
                    print(f" タイムアウト、{attempt+1}/5 回目再試行")
                    time.sleep(2)
                except spotipy.exceptions.SpotifyException as e:
                    print(f" 削除失敗: {e}")
                    break

def safe_add_to_playlist(sp, playlist_id, track_uris):
    """
    トラックをプレイリストにシャッフルして追加する。
    APIの100件制限を考慮し、分割してリトライ処理も行う。
    """
    random.shuffle(track_uris)
    chunk_size = 100
    for i in range(0, len(track_uris), chunk_size):
        chunk = track_uris[i:i+chunk_size]
        for attempt in range(5):
            try:
                sp.playlist_add_items(playlist_id, chunk)
                time.sleep(0.2)
                break
            except requests.exceptions.ReadTimeout:
                print(f" タイムアウト、{attempt+1}/5 回目再試行")
                time.sleep(2)
            except spotipy.exceptions.SpotifyException as e:
                if "rate limit" in str(e).lower():
                    print(" レート制限、1秒待機して再試行")
                    time.sleep(1)
                else:
                    print(f" プレイリスト追加失敗: {e}")
                    break

# -----------------------------
# トラック収集
# -----------------------------

def get_playlist_tracks(sp, playlist_uri):
    """プレイリストURIから全トラックのURIを取得する。"""
    try:
        results = sp.playlist_items(playlist_uri, limit=100)
    except spotipy.exceptions.SpotifyException as e:
        if e.http_status == 404:
            print(f" Playlist not accessible: {playlist_uri}")
            return []
        else:
            raise

    tracks = []
    while results:
        for item in results.get("items", []):
            track = item.get("track")
            if track:
                tracks.append(track["uri"])
        if results.get("next"):
            results = sp.next(results)
        else:
            break
    return tracks

def get_album_tracks(sp, album_uri):
    """アルバムURIから全トラックのURIを取得する。"""
    try:
        results = sp.album_tracks(album_uri, limit=50)
    except spotipy.exceptions.SpotifyException as e:
        if e.http_status == 404:
            print(f" Album not found: {album_uri}")
            return []
        else:
            raise

    tracks = []
    while results:
        for track in results.get("items", []):
            if track:
                tracks.append(track["uri"])
        if results.get("next"):
            results = sp.next(results)
        else:
            break
    return tracks

def search_artist_tracks(sp, artist_name, max_tracks=100):
    """アーティスト名でトラックを検索し、URIのリストを返す。"""
    tracks = []
    limit = 50  # Spotify APIの上限
    offset = 0

    while len(tracks) < max_tracks:
        batch_size = min(limit, max_tracks - len(tracks))
        results = sp.search(
            q=f"artist:{artist_name}",
            type="track",
            limit=batch_size,
            offset=offset
        )
        items = results.get("tracks", {}).get("items", [])
        if not items:
            break

        for t in items:
            tracks.append(t["uri"])

        if len(items) < batch_size:
            break
        offset += batch_size

    return tracks

def collect_tracks(sp, inputs):
    """
    入力（トラックURI、プレイリストURI、アーティスト名）に基づいて
    再生対象のトラックURIリストを作成する。
    """
    all_tracks = []
    print("トラックを収集しています...")
    for item in inputs:
        if item.startswith("spotify:track:"):
            print(f"  - トラックを追加: {item}")
            all_tracks.append(item)
        elif item.startswith("spotify:playlist:"):
            print(f"  - プレイリストからトラックを取得: {item}")
            tracks = get_playlist_tracks(sp, item)
            all_tracks.extend(tracks)
        elif item.startswith("spotify:album:"):
            print(f"  - アルバムからトラックを取得: {item}")
            tracks = get_album_tracks(sp, item)
            all_tracks.extend(tracks)
        else:
            print(f"  - アーティストからトラックを検索: {item}")
            tracks = search_artist_tracks(sp, item, max_tracks=100)
            all_tracks.extend(tracks)
    return all_tracks

# -----------------------------
# メイン処理
# -----------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Spotify URI またはアーティスト名をテンポラリプレイリストに追加して再生"
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        default=[],
        help="Spotify URI（track/playlist/album）またはアーティスト名"
    )
    parser.add_argument(
        "-l", "--list-devices",
        action="store_true",
        help="利用可能なデバイス一覧を表示して終了"
    )
    parser.add_argument(
        "-d", "--device",
        type=str,
        default=None,
        help="再生デバイス名"
    )
    args = parser.parse_args()

    # --- 認証とAPIクライアント準備 ---
    print("Spotifyに接続しています...")
    sp = get_spotify_client()
    print("接続完了。")

    # --- デバイス一覧表示 ---
    if args.list_devices:
        handle_device_listing(sp)
        return

    # --- 入力チェック ---
    if not args.inputs:
        parser.print_help()
        return

    # --- 準備 ---
    user_id = sp.current_user()["id"]
    device_id = get_target_device_id(sp, args.device)
    temp_playlist_id = get_or_create_playlist(sp, user_id, FIXED_PLAYLIST_NAME)

    # --- プレイリスト更新 ---
    print("一時プレイリストをクリアしています...")
    clear_playlist(sp, temp_playlist_id)

    all_tracks = collect_tracks(sp, args.inputs)

    if not all_tracks:
        print("追加する曲が見つかりませんでした。")
        return

    print(f"{len(all_tracks)}曲をプレイリストに追加しています...")
    safe_add_to_playlist(sp, temp_playlist_id, all_tracks)

    # --- 再生開始 ---
    print("再生を開始します...")
    sp.start_playback(device_id=device_id, context_uri=f"spotify:playlist:{temp_playlist_id}")
    print(f"完了: {len(all_tracks)} 曲を再生しました。")

if __name__ == "__main__":
    main()

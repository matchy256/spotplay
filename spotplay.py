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
REDIRECT_URI = "https://asia-east2-spotify-cli-283006.cloudfunctions.net/auth-redirect"
SCOPE = "playlist-modify-public playlist-modify-private user-modify-playback-state user-read-playback-state"

CONFIG_DIR = os.path.expanduser("~/.config/spotplay")
TOKEN_FILE = os.path.join(CONFIG_DIR, "refresh_token.txt")
PLAYLIST_FILE = os.path.join(CONFIG_DIR, "playlist_id.txt")
FIXED_PLAYLIST_NAME = "SpotplayList"

os.makedirs(CONFIG_DIR, exist_ok=True)

# -----------------------------
# refresh_token 取得/保存
# -----------------------------
def get_refresh_token():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            return f.read().strip()
    sp_oauth = SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
        show_dialog=True,
        cache_path=None
    )
    auth_url = sp_oauth.get_authorize_url()
    print(" 以下のURLに別端末でアクセスしてログインしてください：")
    print(auth_url)
    code = input("認可コードを入力してください: ").strip()
    token_info = sp_oauth.get_access_token(code)
    refresh_token = token_info["refresh_token"]
    with open(TOKEN_FILE, "w") as f:
        f.write(refresh_token)
    print(f" refresh_token を {TOKEN_FILE} に保存しました。")
    return refresh_token

# -----------------------------
# Spotipy インスタンス作成（タイムアウト延長）
# -----------------------------
def get_spotify_instance(refresh_token):
    sp_oauth = SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
        cache_path=None
    )
    token_info = sp_oauth.refresh_access_token(refresh_token)

    # requests session with retry and longer timeout
    session = requests.Session()
    retries = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)

    sp = spotipy.Spotify(auth=token_info["access_token"], requests_session=session, requests_timeout=30)
    return sp

# -----------------------------
# アクティブデバイス取得
# -----------------------------
def get_active_device(sp):
    devices = sp.devices()["devices"]
    if not devices:
        raise RuntimeError("アクティブなSpotifyデバイスが見つかりません。")
    for d in devices:
        if d.get("is_active") and not d.get("is_restricted"):
            return d["id"]
    for d in devices:
        if not d.get("is_restricted"):
            return d["id"]
    raise RuntimeError("再生可能なデバイスが見つかりません。")

# -----------------------------
# テンポラリプレイリスト取得/作成
# -----------------------------
def get_or_create_playlist(sp, user_id, name):
    if os.path.exists(PLAYLIST_FILE):
        with open(PLAYLIST_FILE) as f:
            return f.read().strip()
    playlists = sp.current_user_playlists(limit=50)["items"]
    for pl in playlists:
        if pl["name"] == name:
            playlist_id = pl["id"]
            with open(PLAYLIST_FILE, "w") as f:
                f.write(playlist_id)
            return playlist_id
    pl = sp.user_playlist_create(user_id, name, public=False)
    playlist_id = pl["id"]
    with open(PLAYLIST_FILE, "w") as f:
        f.write(playlist_id)
    return playlist_id

# -----------------------------
# プレイリスト全削除（小分け＋リトライ対応）
# -----------------------------
def clear_playlist(sp, playlist_id):
    while True:
        items = sp.playlist_items(playlist_id, fields="items.track.id,total", limit=50)["items"]
        track_ids = [t["track"]["id"] for t in items if t["track"]]
        if not track_ids:
            break
        for i in range(0, len(track_ids), 50):
            chunk = track_ids[i:i+50]
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

# -----------------------------
# プレイリストの曲取得
# -----------------------------
def get_playlist_tracks(sp, playlist_uri):
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
        for item in results["items"]:
            track = item.get("track")
            if track:
                tracks.append(track["uri"])
        if results["next"]:
            results = sp.next(results)
        else:
            break
    return tracks

# -----------------------------
# アーティスト検索
# -----------------------------
def search_artist_tracks(sp, artist_name, max_tracks=100):
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

        # アーティスト名完全一致チェックはやめる
        for t in items:
            tracks.append(t["uri"])

        if len(items) < batch_size:
            break  # もう次ページはない
        offset += batch_size

    return tracks

# -----------------------------
# プレイリストに安全に追加
# -----------------------------
def safe_add_to_playlist(sp, playlist_id, track_uris):
    random.shuffle(track_uris)
    chunk_size = 100
    for i in range(0, len(track_uris), chunk_size):
        for attempt in range(5):
            try:
                sp.playlist_add_items(playlist_id, track_uris[i:i+chunk_size])
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
# メイン
# -----------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Spotify URI またはアーティスト名をテンポラリプレイリストに追加して再生"
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        default=[],
        help="Spotify URI（track/playlist）またはアーティスト名"
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

    refresh_token = get_refresh_token()
    sp = get_spotify_instance(refresh_token)

    if args.list_devices:
        devices = sp.devices().get('devices', [])
        if not devices:
            print("利用可能なデバイスが見つかりません。")
            return
        print("利用可能なデバイス:")
        for device in devices:
            active_str = " (アクティブ)" if device.get('is_active') else ""
            print(f"  - {device['name']}{active_str}")
        return

    if not args.inputs:
        parser.print_help()
        return

    user_id = sp.current_user()["id"]
    device_id = None
    if args.device:
        devices = sp.devices().get('devices', [])
        for d in devices:
            if d['name'].lower() == args.device.lower():
                device_id = d['id']
                print(f"{d['name']} を再生デバイスに設定しました。")
                break
        if not device_id:
            print(f"警告: デバイス '{args.device}' が見つかりません。アクティブなデバイスで再生します。")

    if not device_id:
        device_id = get_active_device(sp)

    temp_playlist_id = get_or_create_playlist(sp, user_id, FIXED_PLAYLIST_NAME)
    clear_playlist(sp, temp_playlist_id)

    all_tracks = []

    for item in args.inputs:
        if item.startswith("spotify:track:"):
            all_tracks.append(item)
        elif item.startswith("spotify:playlist:"):
            tracks = get_playlist_tracks(sp, item)
            all_tracks.extend(tracks)
        else:
            tracks = search_artist_tracks(sp, item, max_tracks=100)
            all_tracks.extend(tracks)

    if not all_tracks:
        print(" 追加する曲が見つかりませんでした。")
        return

    safe_add_to_playlist(sp, temp_playlist_id, all_tracks)
    sp.start_playback(device_id=device_id, context_uri=f"spotify:playlist:{temp_playlist_id}")
    print(f" {len(all_tracks)} 曲をテンポラリプレイリストに追加して再生しました。")

if __name__ == "__main__":
    main()

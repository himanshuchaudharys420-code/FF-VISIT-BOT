import sys, os, asyncio, json, time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

import GOJOXGEN

BASE_DIR = CURRENT_DIR

def set_region_config(region="IND"):
    GOJOXGEN.REGION = region
    if region == "IND":
        GOJOXGEN.DEFAULT_CLIENT_URL = "https://client.ind.freefiremobile.com"
        GOJOXGEN.BIO_URL = "https://client.ind.freefiremobile.com/UpdateSocialBasicInfo"
        GOJOXGEN.LOGIN_HOST = "loginbp.ppmainecoonghj.com"
    else:
        GOJOXGEN.DEFAULT_CLIENT_URL = "https://clientbp.ppmainecoonghj.com"
        GOJOXGEN.BIO_URL = "https://clientbp.ppmainecoonghj.com/UpdateSocialBasicInfo"
        GOJOXGEN.LOGIN_HOST = "loginbp.ppmainecoonghj.com"
    GOJOXGEN.MAJOR_LOGIN_URL = f"https://{GOJOXGEN.LOGIN_HOST}/MajorLogin"

def generate_one(region="IND"):
    set_region_config(region)
    device_id = "02-" + str(os.urandom(16).hex())
    uid, password = GOJOXGEN.guest_register(device_id, max_retries=10)
    if not uid:
        return None

    token_data = GOJOXGEN.guest_token(uid, max_retries=10)
    if not token_data:
        return None

    open_id = token_data["open_id"]
    access_token = token_data["access_token"]
    nickname = GOJOXGEN.generate_nickname()
    sync_ts, sync_time_str = GOJOXGEN.get_server_time()

    account_id = GOJOXGEN.major_register(open_id, access_token, nickname, sync_ts, max_retries=5)
    if not account_id:
        return None

    login_payload = GOJOXGEN.PyL(access_token, open_id, sync_time_str)
    ml = GOJOXGEN.MajorLogin(login_payload, sync_ts, max_retries=5)
    if not ml:
        return None

    ad = GOJOXGEN.ExtractMajorLogin(ml)
    if not ad or "jwt" not in ad or not ad["jwt"]:
        return None

    jwt = ad["jwt"]
    return {
        "uid": str(uid),
        "account_id": str(account_id),
        "name": str(nickname),
        "token": jwt,
        "jwt": jwt,
        "region": region,
        "created_at": int(time.time()),
        "password": str(password)
    }

def _save_to_file(new_tokens, target_file):
    if not new_tokens:
        return 0
    existing = []
    if os.path.exists(target_file):
        try:
            with open(target_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = []

    now = time.time()
    fresh_existing = [it for it in existing if isinstance(it, dict) and it.get("created_at", 0) > (now - 25200)]
    seen_tokens = {it["token"] for it in new_tokens if "token" in it}
    deduped_existing = [it for it in fresh_existing if it.get("token") not in seen_tokens]
    updated = new_tokens + deduped_existing
    
    tmp_file = target_file + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(updated, f, indent=2)
    if os.path.exists(target_file):
        try: os.remove(target_file)
        except Exception: pass
    os.replace(tmp_file, target_file)
    return len(updated)

import concurrent.futures, threading

def generate_batch_sync(count=50, region="IND", max_workers=None):
    set_region_config(region)
    target_file = os.path.join(BASE_DIR, f"token_{region.lower()}.json")
    generated = []
    gen_lock = threading.Lock()
    stop_flag = threading.Event()
    
    # Pre-fetch proxies in background
    GOJOXGEN.fetch_fresh_proxies()

    def worker_loop(wid):
        while not stop_flag.is_set():
            with gen_lock:
                if len(generated) >= count:
                    stop_flag.set()
                    break
            try:
                entry = generate_one(region)
                if entry:
                    with gen_lock:
                        if len(generated) < count:
                            generated.append(entry)
                            print(f"[{region}] [PROGRESS] {len(generated)}/{count} IDs generated", flush=True)
                            if len(generated) % 5 == 0 or len(generated) >= count:
                                tot = _save_to_file(generated, target_file)
                                print(f"[{region}] [AUTO-SAVED] Stock updated: {len(generated)}/{count} IDs saved (Total in pool: {tot})", flush=True)
                            if len(generated) >= count:
                                stop_flag.set()
                                break
                else:
                    time.sleep(2.0)
            except Exception:
                time.sleep(2.0)

    if max_workers is None:
        # Double threads for IND as requested by user
        max_workers = 6 if region == "IND" else 3
    max_workers = min(max_workers, count)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(worker_loop, i) for i in range(max_workers)]
        concurrent.futures.wait(futures)

    import gc
    gc.collect()

    if generated:
        tot = _save_to_file(generated, target_file)
        print(f"[DONE] {len(generated)} IDs added. Total stock: {tot}", flush=True)
        return tot
    
    print("[DONE] 0 IDs added.", flush=True)
    return 0

async def generate_batch(count=50, region="IND"):
    return await asyncio.to_thread(generate_batch_sync, count, region)

if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    region = sys.argv[2].upper() if len(sys.argv) > 2 else "IND"
    asyncio.run(generate_batch(count, region))

from flask import Flask, request, jsonify
import asyncio
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from google.protobuf.json_format import MessageToJson
import binascii
import aiohttp
import requests
import json
import like_pb2
import like_count_pb2
import uid_generator_pb2
from google.protobuf.message import DecodeError
import base64
import time
import hashlib

app = Flask(__name__)

# 🔐 SECRET (same as your bot)
SECRET = "mysecret123"

# 🔐 Generate valid passwords (current + previous minute)
def valid_passwords():
    now = int(time.time() // 60)
    passwords = []
    for t in [now, now - 1]:
        raw = SECRET + str(t)
        passwords.append(hashlib.sha256(raw.encode()).hexdigest()[:6])
    return passwords


def load_tokens():
    try:
        with open("tokens.json", "r") as f:
            tokens = json.load(f)
        return tokens
    except Exception as e:
        app.logger.error(f"Error loading tokens: {e}")
        return None


def encrypt_message(plaintext):
    try:
        key = b'Yg&tc%DEuh6%Zc^8'
        iv = b'6oyZDr22E3ychjM%'
        cipher = AES.new(key, AES.MODE_CBC, iv)
        padded_message = pad(plaintext, AES.block_size)
        encrypted_message = cipher.encrypt(padded_message)
        return binascii.hexlify(encrypted_message).decode('utf-8')
    except Exception as e:
        app.logger.error(f"Error encrypting message: {e}")
        return None


def create_protobuf_message(user_id, region):
    try:
        message = like_pb2.like()
        message.uid = int(user_id)
        message.region = region
        return message.SerializeToString()
    except Exception as e:
        app.logger.error(f"Error creating protobuf message: {e}")
        return None


async def send_request(encrypted_uid, token, url):
    try:
        edata = bytes.fromhex(encrypted_uid)
        headers = {
            'User-Agent': "Dalvik/2.1.0",
            'Authorization': f"Bearer {token}",
            'Content-Type': "application/x-www-form-urlencoded"
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=edata, headers=headers) as response:
                return await response.text()
    except Exception as e:
        app.logger.error(f"Exception in send_request: {e}")
        return None


async def send_multiple_requests(uid, server_name, url):
    try:
        protobuf_message = create_protobuf_message(uid, server_name)
        encrypted_uid = encrypt_message(protobuf_message)

        tokens = load_tokens()
        if not tokens:
            return None

        tasks = []
        for i in range(100):
            token = tokens[i % len(tokens)]  # ✅ FIXED FORMAT
            tasks.append(send_request(encrypted_uid, token, url))

        return await asyncio.gather(*tasks)
    except Exception as e:
        app.logger.error(f"Exception: {e}")
        return None


def create_protobuf(uid):
    try:
        message = uid_generator_pb2.uid_generator()
        message.saturn_ = int(uid)
        message.garena = 1
        return message.SerializeToString()
    except Exception as e:
        return None


def enc(uid):
    protobuf_data = create_protobuf(uid)
    return encrypt_message(protobuf_data)


def make_request(encrypt, server_name, token):
    try:
        if server_name == "IND":
            url = "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
        else:
            url = "https://client.us.freefiremobile.com/GetPlayerPersonalShow"

        edata = bytes.fromhex(encrypt)
        headers = {'Authorization': f"Bearer {token}"}

        response = requests.post(url, data=edata, headers=headers, verify=False)
        binary = bytes.fromhex(response.content.hex())

        items = like_count_pb2.Info()
        items.ParseFromString(binary)
        return items
    except Exception as e:
        app.logger.error(f"Error: {e}")
        return None


@app.route('/like', methods=['GET'])
def handle_requests():

    # 🔐 PASSWORD CHECK
    user_pass = request.args.get("password")
    if not user_pass or user_pass not in valid_passwords():
        return jsonify({
            "status": 0,
            "message": "Invalid or missing password"
        }), 403

    uid = request.args.get("uid")
    if not uid:
        return jsonify({"error": "UID is required"}), 400

    try:
        tokens = load_tokens()
        if not tokens:
            return jsonify({"error": "No tokens found"}), 500

        token = tokens[0]

        # Detect region
        payload = token.split('.')[1]
        payload += '=' * (-len(payload) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload))
        server_name = decoded.get('lock_region', 'IND')

        encrypted_uid = enc(uid)

        before = make_request(encrypted_uid, server_name, token)
        data_before = json.loads(MessageToJson(before))
        before_like = int(data_before.get('AccountInfo', {}).get('Likes', 0))

        # Send likes
        if server_name == "IND":
            url = "https://client.ind.freefiremobile.com/LikeProfile"
        else:
            url = "https://client.us.freefiremobile.com/LikeProfile"

        asyncio.run(send_multiple_requests(uid, server_name, url))

        after = make_request(encrypted_uid, server_name, token)
        data_after = json.loads(MessageToJson(after))
        account = data_after.get('AccountInfo', {})

        after_like = int(account.get('Likes', 0))
        player_name = account.get('PlayerNickname', '')

        return jsonify({
            "LikesGivenByAPI": after_like - before_like,
            "LikesafterCommand": after_like,
            "LikesbeforeCommand": before_like,
            "PlayerNickname": player_name,
            "Region": server_name,
            "UID": uid,
            "status": 1
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True)

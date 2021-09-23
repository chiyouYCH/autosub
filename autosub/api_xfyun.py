#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Defines Xun Fei Yun API used by autosub.
"""
# Import built-in modules
import datetime
import hashlib
import base64
import hmac
import json
from urllib.parse import urlencode
import ssl
from email.utils import formatdate
import time
from datetime import datetime
from time import mktime

# Import third-party modules
import websocket
import _thread

# Any changes to the path and your own modules
from autosub import constants
from autosub import exceptions


def create_xfyun_url(
        api_key,
        api_secret,
        api_address=constants.XFYUN_SPEECH_WEBAPI_URL
):
    """
    Function for creating authorization for Xun Fei Yun Speech-to-Text Websocket API.
    """
    request_location = "/v2/iat"
    result_url = "wss://" + api_address + request_location
    now = datetime.now()
    stamp = mktime(now.timetuple())
    date = formatdate(timeval=stamp, localtime=False, usegmt=True)

    signature_origin = "host: " + api_address + "\n"
    signature_origin += "date: " + date + "\n"
    signature_origin += "GET " + request_location + " HTTP/1.1"
    signature_sha = hmac.new(
        api_secret.encode('utf-8'),
        signature_origin.encode('utf-8'),
        digestmod=hashlib.sha256).digest()

    signature_sha = base64.b64encode(signature_sha).decode(encoding='utf-8')
    authorization_origin = "api_key=\"{api_key}\", " \
                           "algorithm=\"hmac-sha256\", " \
                           "headers=\"host date request-line\", " \
                           "signature=\"{sign}\"".format(
                               api_key=api_key,
                               sign=signature_sha)
    authorization = base64.b64encode(
        authorization_origin.encode('utf-8')).decode(encoding='utf-8')
    verification = {
        "authorization": authorization,
        "date": date,
        "host": api_address
    }
    result_url = result_url + '?' + urlencode(verification)
    return result_url


def get_xfyun_transcript(
        result_dict,
        delete_chars=None):
    """
    Function for getting transcript from Xun Fei Yun Speech-to-Text Websocket API result dictionary.
    Reference: https://www.xfyun.cn/doc/asr/voicedictation/API.html
    """
    try:
        code = result_dict["code"]
        if code != 0:
            raise exceptions.SpeechToTextException(
                json.dumps(result_dict, indent=4, ensure_ascii=False))
        result = ""
        for item in result_dict["data"]["result"]["ws"]:
            result = result + item["cw"][0]["w"]
        if delete_chars:
            result = result.translate(
                str.maketrans(delete_chars, " " * len(delete_chars)))
            return result.rstrip(" ")
        return result
    except (KeyError, TypeError):
        return ""


class XfyunWebSocketAPI:  # pylint: disable=too-many-instance-attributes, too-many-arguments, unnecessary-lambda
    """
    Class for performing speech-to-text using Xun Fei Yun Speech-to-Text Websocket API.
    Reference: https://www.xfyun.cn/doc/asr/voicedictation/API.html
               #%E6%8E%A5%E5%8F%A3%E8%B0%83%E7%94%A8%E6%B5%81%E7%A8%8B
               https://stackoverflow.com/questions/26980966/using-a-websocket-client-as-a-class-in-python
    """
    def __init__(self,
                 app_id,
                 api_key,
                 api_secret,
                 api_address,
                 business_args,
                 is_full_result=False,
                 delete_chars=None):
        self.common_args = {"app_id": app_id}
        self.api_key = api_key
        self.api_secret = api_secret
        self.api_address = api_address
        self.business_args = business_args
        self.is_full_result = is_full_result
        self.delete_chars = delete_chars
        self.data = {"status": 0,
                     "format": "audio/L16;rate=16000",
                     "encoding": "raw",
                     "audio": ""}
        self.transcript = ""
        self.result_list = []
        self.filename = None
        self.web_socket_app = None

    def __call__(self, filename):
        if self.is_full_result:
            self.result_list = []
        else:
            self.transcript = ""
        self.filename = filename
        websocket.enableTrace(False)
        # Ref: https://stackoverflow.com/questions/26980966
        # /using-a-websocket-client-as-a-class-in-python
        self.web_socket_app = websocket.WebSocketApp(
            create_xfyun_url(
                api_key=self.api_key,
                api_secret=self.api_secret,
                api_address=self.api_address),
            on_message=lambda web_socket, msg: self.on_message(web_socket, msg),
            on_error=lambda web_socket, msg: self.on_error(web_socket, msg),
            on_close=lambda web_socket: self.on_close(web_socket),
            on_open=lambda web_socket: self.on_open(web_socket))
        ## 建立长连接
        self.web_socket_app.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
        if self.is_full_result:
            return self.result_list
        return self.transcript

    def on_message(self, web_socket, result):  # pylint: disable=unused-argument
        """
        Process the message received from WebSocket.
        """
        try:
            web_socket_result = json.loads(result)
        except ValueError:
            return
        if not self.is_full_result:
            self.transcript = self.transcript + \
                              get_xfyun_transcript(
                                  result_dict=web_socket_result,
                                  delete_chars=self.delete_chars)
        else:
            self.result_list.append(web_socket_result)

    def on_error(self, web_socket, error):  # pylint: disable=no-self-use
        """
        Process the error from WebSocket.
        """
        raise exceptions.SpeechToTextException(error)

    def on_close(self, web_socket):  # pylint: disable=no-self-use, unused-argument
        """
        Process the connection close from WebSocket.
        """
        return

    def on_open(self, web_socket):
        """
        Process the connection open from WebSocket.
        """
        def run():
            frame_size = 8000  # 每一帧的音频大小
            interval = 0.04  # 发送音频间隔(单位:s)
            status = 0  # 音频的状态信息，标识音频是第一帧，还是中间帧、最后一帧
            with open(self.filename, "rb") as audio_file:
                while True:
                    buf = audio_file.read(frame_size)
                    # 文件结束
                    if not buf:
                        status = 2
                    self.data["audio"] = str(base64.b64encode(buf), "utf-8")
                    # 第一帧处理
                    # 发送第一帧音频，带business 参数
                    # appid 必须带上，只需第一帧发送
                    if status == 0:
                        self.data["status"] = 0
                        web_socket_data = {
                            "common": self.common_args,
                            "business": self.business_args,
                            "data": self.data}
                        status = 1
                    # 中间帧处理
                    elif status == 1:
                        self.data["status"] = 1
                        web_socket_data = {"data": self.data}
                    # 最后一帧处理
                    elif status == 2:
                        self.data["status"] = 2
                        web_socket_data = {"data": self.data}
                        web_socket_json = json.dumps(web_socket_data)
                        web_socket.send(web_socket_json)
                        time.sleep(1)
                        break

                    web_socket_json = json.dumps(web_socket_data)
                    web_socket.send(web_socket_json)
                    # 模拟音频采样间隔
                    time.sleep(interval)
            web_socket.close()
        _thread.start_new_thread(run, ())


# if __name__ == "__main__":
#     # 测试时候在此处正确填写相关信息即可运行
#     time1 = datetime.now()
#     web_socket_result_obj = XfyunWebSocketAPI(
#         app_id="",
#         api_key="",
#         api_secret="",
#         api_address=constants.XFYUN_SPEECH_WEBAPI_URL,
#         business_args={"language": "zh_cn",
#                        "domain": "iat",
#                        "accent": "mandarin"},
#         is_full_result=False,
#         is_keep=True)
#
#     print(web_socket_result_obj(filename=r".pcm"))
#     time2 = datetime.now()
#     print(time2 - time1)

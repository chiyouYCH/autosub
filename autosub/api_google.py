#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Defines Google API used by autosub.
"""
# Import built-in modules
import os
import base64
import json

# Import third-party modules
import requests

# Any changes to the path and your own modules
from autosub import exceptions
from autosub import constants

if constants.IS_GOOGLECLOUDCLIENT:
    from google.cloud import speech_v1
    from google.protobuf.json_format import MessageToDict
    from google.cloud.speech_v1 import types
else:
    speech_v1 = None  # pylint: disable=invalid-name
    MessageToDict = None  # pylint: disable=invalid-name
    enums = None  # pylint: disable=invalid-name


def google_ext_to_enc(
        extension,
        is_string=True):
    """
    File extension to audio encoding.
    """
    ext = extension.lower()
    if is_string:
        if ext.endswith(".flac"):
            encoding = "FLAC"
        elif ext.endswith(".mp3"):
            encoding = "MP3"
        elif ext.endswith(".wav")\
                or ext.endswith(".pcm"):
            # regard WAV as PCM
            encoding = "LINEAR16"
        elif ext.endswith(".ogg"):
            encoding = "OGG_OPUS"
        else:
            encoding = ""

    else:
        # https://cloud.google.com/speech-to-text/docs/reference/rest/v1p1beta1/RecognitionConfig?hl=zh-cn#AudioEncoding
        if ext.endswith(".flac"):
            encoding = \
                enums.RecognitionConfig.AudioEncoding.FLAC
            # encoding = 2
        elif ext.endswith(".mp3"):
            encoding = \
                enums.RecognitionConfig.AudioEncoding.MP3
            # encoding = 8
        elif ext.endswith(".wav")\
                or extension.lower().endswith(".pcm"):
            # regard WAV as PCM
            encoding = \
                enums.RecognitionConfig.AudioEncoding.LINEAR16
            # encoding = 1
        elif ext.endswith(".ogg"):
            encoding = \
                enums.RecognitionConfig.AudioEncoding.OGG_OPUS
            # encoding = 6
        else:
            encoding = \
                enums.RecognitionConfig.AudioEncoding.ENCODING_UNSPECIFIED
            # encoding = 0

    return encoding


def google_enc_to_ext(  # pylint: disable=too-many-branches
        encoding):
    """
    Audio encoding to file extension.
    """
    if isinstance(encoding, str):
        if encoding == "FLAC":
            extension = ".flac"
        elif encoding == "MP3":
            extension = ".mp3"
        elif encoding == "LINEAR16":
            extension = ".wav"
        elif encoding == "OGG_OPUS":
            extension = ".ogg"
        else:
            extension = ".flac"

    elif isinstance(encoding, int):
        # https://cloud.google.com/speech-to-text/docs/reference/rest/v1p1beta1/RecognitionConfig?hl=zh-cn#AudioEncoding
        if encoding == 2:
            extension = ".flac"
        elif encoding == 8:
            extension = ".mp3"
        elif encoding == 1:
            extension = ".wav"
        elif encoding == 6:
            extension = ".ogg"
        else:
            extension = ".flac"

    else:
        extension = ".flac"

    return extension


def get_google_speech_v2_transcript(
        min_confidence,
        result_dict):
    """
    Function for getting transcript from Google Speech-to-Text V2 json format string result.
    """
    if 'result' in result_dict and result_dict['result'] \
            and 'alternative' in result_dict['result'][0] \
            and result_dict['result'][0]['alternative'] \
            and 'transcript' in result_dict['result'][0]['alternative'][0]:
        text = result_dict['result'][0]['alternative'][0]['transcript']

        if 'confidence' in result_dict['result'][0]['alternative'][0]:
            confidence = \
                float(result_dict['result'][0]['alternative'][0]['confidence'])
            if confidence > min_confidence:
                result = text[:1].upper() + text[1:]
                result = result.replace('’', '\'')
                return result
            return None

        # can't find confidence in json
        # means it's 100% confident
        result = text[:1].upper() + text[1:]
        result = result.replace('’', '\'')
        return result

    return None


def get_gcsv1p1beta1_transcript(
        min_confidence,
        result_dict):
    """
    Function for getting transcript from Google Cloud Speech-to-Text V1P1Beta1 result dictionary.
    """
    if 'results' in result_dict and result_dict['results'] \
            and 'alternatives' in result_dict['results'][0] \
            and result_dict['results'][0]['alternatives'] \
            and 'transcript' in result_dict['results'][0]['alternatives'][0]:
        result_dict = result_dict['results'][0]['alternatives'][0]

        if 'transcript' not in result_dict:
            return None

    else:
        if not result_dict:
            # if api returned empty json, don't throw the exception
            return None
        raise exceptions.SpeechToTextException(
            json.dumps(result_dict, indent=4, ensure_ascii=False))

    if 'confidence' in result_dict:
        confidence = \
            float(result_dict['confidence'])
        if confidence > min_confidence:
            result_dict = result_dict['transcript']
            result = result_dict[:1].upper() + result_dict[1:]
            result = result.replace('’', '\'')
            return result
        return None

    # can't find confidence in json
    # means it's 100% confident
    result_dict = result_dict['transcript']
    result = result_dict[:1].upper() + result_dict[1:]
    result = result.replace('’', '\'')
    return result


class GoogleSpeechV2:  # pylint: disable=too-few-public-methods
    """
    Class for performing speech-to-text using Google Speech V2 API for an input FLAC file.
    """
    def __init__(self,
                 api_url,
                 headers,
                 min_confidence=0.0,
                 retries=3,
                 is_keep=False,
                 is_full_result=False):
        # pylint: disable=too-many-arguments
        self.min_confidence = min_confidence
        self.retries = retries
        self.api_url = api_url
        self.is_keep = is_keep
        self.headers = headers
        self.is_full_result = is_full_result

    def __call__(self, filename):
        try:  # pylint: disable=too-many-nested-blocks
            audio_file = open(filename, mode='rb')
            audio_data = audio_file.read()
            audio_file.close()
            if not self.is_keep:
                os.remove(filename)
            for _ in range(self.retries):
                try:
                    result = requests.post(self.api_url, data=audio_data, headers=self.headers)
                except requests.exceptions.ConnectionError:
                    continue

                # receive several results delimited by LF
                result_list = result.content.decode('utf-8').split("\n")
                # get the one with valid content
                for line in result_list:
                    try:
                        line_dict = json.loads(line)
                        transcript = get_google_speech_v2_transcript(
                            self.min_confidence,
                            line_dict)
                        if transcript:
                            # make sure it is the valid transcript
                            if not self.is_full_result:
                                return transcript
                            return line_dict

                    except (ValueError, IndexError):
                        # no result
                        continue

                # Every line of the result can't be loaded to json
                return None

        except KeyboardInterrupt:
            return None

        return None


def gcsv1p1beta1_service_client(
        filename,
        is_keep,
        config,
        min_confidence,
        is_full_result=False):
    """
    Function for performing Speech-to-Text
    using Google Cloud Speech-to-Text V1P1Beta1 API client for an input FLAC file.
    """
    try:  # pylint: disable=too-many-nested-blocks
        audio_file = open(filename, mode='rb')
        audio_data = audio_file.read()
        audio_file.close()
        if not is_keep:
            os.remove(filename)

        # https://cloud.google.com/speech-to-text/docs/quickstart-client-libraries
        # https://cloud.google.com/speech-to-text/docs/basics
        # https://cloud.google.com/speech-to-text/docs/reference/rpc/google.cloud.speech.v1p1beta1#google.cloud.speech.v1p1beta1.SpeechRecognitionResult
        client = speech_v1.SpeechClient()
        audio_dict = {"content": audio_data}
        # recognize_response = client.recognize(config, audio_dict)
        recognize_response = []
        result_dict = MessageToDict(
            recognize_response,
            preserving_proto_field_name=True)

        if not is_full_result:
            return get_gcsv1p1beta1_transcript(min_confidence, result_dict)
        return result_dict

    except KeyboardInterrupt:
        return None


class GCSV1P1Beta1URL:  # pylint: disable=too-few-public-methods, duplicate-code
    """
    Class for performing Speech-to-Text
    using Google Cloud Speech-to-Text V1P1Beta1 API URL for an input FLAC file.
    """
    def __init__(self,
                 config,
                 api_url=None,
                 headers=None,
                 min_confidence=0.0,
                 retries=3,
                 is_keep=False,
                 is_full_result=False):
        # pylint: disable=too-many-arguments
        self.config = config
        self.api_url = api_url
        self.headers = headers
        self.min_confidence = min_confidence
        self.retries = retries
        self.is_keep = is_keep
        self.is_full_result = is_full_result

    def __call__(self, filename):
        try:  # pylint: disable=too-many-nested-blocks
            audio_file = open(filename, mode='rb')
            audio_data = audio_file.read()
            audio_file.close()
            if not self.is_keep:
                os.remove(filename)

            for _ in range(self.retries):
                # https://cloud.google.com/speech-to-text/docs/quickstart-protocol
                # https://cloud.google.com/speech-to-text/docs/base64-encoding
                # https://gist.github.com/bretmcg/07e0efe27611d7039c2e4051b4354908
                audio_dict = \
                    {"content": base64.b64encode(audio_data).decode("utf-8")}
                request_data = {"config": self.config, "audio": audio_dict}
                config_json = json.dumps(request_data, ensure_ascii=False)

                try:
                    requests_result = \
                        requests.post(self.api_url, data=config_json, headers=self.headers)

                except requests.exceptions.ConnectionError:
                    continue

                requests_result_json = requests_result.content.decode('utf-8')

                try:
                    result_dict = json.loads(requests_result_json)
                except ValueError:
                    # no result
                    continue

                if not self.is_full_result:
                    return get_gcsv1p1beta1_transcript(self.min_confidence, result_dict)
                return result_dict

        except KeyboardInterrupt:
            return None

        return None

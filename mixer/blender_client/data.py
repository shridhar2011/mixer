"""
This module handles generic updates using the blender_data package.

The goal for Mixer is to replace all code specific to entities (camera, light, material, ...) by this generic update
mechanism.
"""

import logging
from typing import List, Tuple

from mixer.blender_data.json_codec import Codec
from mixer.blender_data.proxy import BpyIDProxy
from mixer.broadcaster import common
from mixer.log_utils import log_traceback
from mixer.share_data import share_data

logger = logging.getLogger(__name__)

# No explicit creations here.
# The creations are perfomed as part of an update of an item that does not exist.


def build_data_remove(buffer):
    if not share_data.use_experimental_sync():
        return

    collection_name, index = common.decode_string(buffer, 0)
    key, index = common.decode_string(buffer, index)
    logger.info("build_data_remove: %s[%s]", collection_name, key)
    # Update through the proxy so that it updates itself and does not trigger removals
    share_data.proxy.remove_one(collection_name, key)

    # TODO temporary until VRtist protocol uses Blenddata instead of blender_objects & co
    share_data.set_dirty()


class InvalidPath(Exception):
    pass


def blenddata_path(proxy):
    if proxy._blenddata_path is None:
        logger.error("blenddata_path is None. _data is ...")
        logger.error(f"... {proxy._data}")
        raise InvalidPath

    collection_name, key, *path = proxy._blenddata_path
    if collection_name is None or key is None:
        logger.error("invalid blenddata_path : %s[%s], ", collection_name, key)
        raise InvalidPath

    if path:
        logger.error("blenddata_path %s[%s] has non empty tail %s", collection_name, key, path)
        raise InvalidPath

    return collection_name, key


#
# WARNING There ara duplicate keys in blendata collections with linked blendfiles
#
def build_data_update(buffer):
    if not share_data.use_experimental_sync():
        return

    buffer, _ = common.decode_string(buffer, 0)
    codec = Codec()
    try:
        id_proxy = codec.decode(buffer)
        try:
            collection_name, key = blenddata_path(id_proxy)
        except InvalidPath:
            logger.error("... update ignored")
            return

        uuid = id_proxy.mixer_uuid()
        logger.info("build_data_update: %s[%s] %s", collection_name, key, uuid)
        share_data.proxy.update_one(id_proxy)
        # TODO temporary until VRtist protocol uses Blenddata instead of blender_objects & co
        share_data.set_dirty()
    except Exception:
        logger.error("Exception during build_data_update")
        log_traceback(logger.error)
        logger.error(f"During processing of buffer with blenddata_path {id_proxy._blenddata_path}")
        logger.error(buffer[0:200])
        logger.error("...")
        logger.error(buffer[-200:0])
        logger.error(f"Creation or update of bpy.data.{collection_name}[{key}] was ignored")


def send_data_removals(removals: List[Tuple[str, str]]):
    if not share_data.use_experimental_sync():
        return

    for collection_name, key in removals:
        logger.info("send_removal: %s[%s]", collection_name, key)
        buffer = common.encode_string(collection_name) + common.encode_string(key)
        command = common.Command(common.MessageType.BLENDER_DATA_REMOVE, buffer, 0)
        share_data.client.add_command(command)


def send_data_updates(updates: List[BpyIDProxy]):
    if not share_data.use_experimental_sync():
        return
    if not updates:
        return
    codec = Codec()
    for proxy in updates:
        # We send an ID, so we need to make sure that it includes a bp.data collection name
        # and the associated key
        try:
            collection_name, key = blenddata_path(proxy)
        except InvalidPath:
            logger.error("... update ignored")
            continue

        logger.info("send_data_update %s[%s]", collection_name, key)

        try:
            encoded_proxy = codec.encode(proxy)
        except InvalidPath:
            logger.error("send_update: Exception :")
            log_traceback(logger.error)
            logger.error(f"while processing bpy.data.{collection_name}[{key}]:")

        # For BpyIdProxy, the target is encoded in the proxy._blenddata_path
        buffer = common.encode_string(encoded_proxy)
        command = common.Command(common.MessageType.BLENDER_DATA_UPDATE, buffer, 0)
        share_data.client.add_command(command)

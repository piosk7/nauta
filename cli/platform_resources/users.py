#
# INTEL CONFIDENTIAL
# Copyright (c) 2018 Intel Corporation
#
# The source code contained or described herein and all documents related to
# the source code ("Material") are owned by Intel Corporation or its suppliers
# or licensors. Title to the Material remains with Intel Corporation or its
# suppliers and licensors. The Material contains trade secrets and proprietary
# and confidential information of Intel or its suppliers and licensors. The
# Material is protected by worldwide copyright and trade secret laws and treaty
# provisions. No part of the Material may be used, copied, reproduced, modified,
# published, uploaded, posted, transmitted, distributed, or disclosed in any way
# without Intel's prior express written permission.
#
# No license under any patent, copyright, trade secret or other intellectual
# property right is granted to or conferred upon you by disclosure or delivery
# of the Materials, either expressly, by implication, inducement, estoppel or
# otherwise. Any license under such intellectual property rights must be express
# and approved by Intel in writing.
#

from typing import List

from kubernetes import config, client
from kubernetes.client.rest import ApiException

from platform_resources.user_model import User
from platform_resources.runs import list_runs
import platform_resources.user_model as model

from util.logger import initialize_logger
from util.k8s import k8s_proxy_context_manager
from util.exceptions import K8sProxyCloseError
from util.app_names import DLS4EAppNames
from logs_aggregator.k8s_es_client import K8sElasticSearchClient

logger = initialize_logger(__name__)

API_GROUP_NAME = 'aipg.intel.com'
USERS_PLURAL = 'users'
USERS_VERSION = 'v1'


def list_users() -> List[User]:
    """
    Return list of users.
    :return: List of User objects
    """
    logger.debug('Listing users.')
    config.load_kube_config()
    api = client.CustomObjectsApi(client.ApiClient())

    raw_users = api.list_cluster_custom_object(group=API_GROUP_NAME, plural=USERS_PLURAL,
                                               version=USERS_VERSION)

    users = [User.from_k8s_response_dict(user_dict) for user_dict in raw_users['items']]

    # Get experiment runs for each user
    # TODO: CHANGE IMPLEMENTATION TO USE AGGREGATED USER DATA AFTER CAN-366
    runs = list_runs()
    user_map = {user.name: user for user in users}
    for run in runs:
        user_map[run.submitter].experiment_runs.append(run)

    return users


def purge_user(username: str):
    """
    Removes all system's artifacts that belong to a removed user.
    K8s objects are removed during removal of a namespace.
    :param username: name of a user for which artifacts should be removed
    It throws exception in case of any problems detected during removal of a user
    """
    # remove data from elasticsearch
    try:
        with k8s_proxy_context_manager.K8sProxy(DLS4EAppNames.ELASTICSEARCH) as proxy:
            es_client = K8sElasticSearchClient(host="127.0.0.1", port=proxy.container_port,
                                               verify_certs=False, use_ssl=False)
            es_client.delete_logs_for_namespace(username)
    except K8sProxyCloseError as exe:
        logger.exception("Error during closing of a proxy for elasticsearch.")
        raise exe
    except Exception as exe:
        logger.exception("Error during removal of data from elasticsearch")
        raise exe

    # remove experiments/runs data
    # TODO


def get_user_data(username: str) -> model.User:
    """
    Return users data.
    :param username: name of a user
    :return: User object with users data. If user doesn't exist - it returns None
    In case of any problems during gathering users data it throws an exception
    """
    try:
        config.load_kube_config()
        api = client.CustomObjectsApi(client.ApiClient())

        user_data = api.get_cluster_custom_object(group=API_GROUP_NAME, version=USERS_VERSION,
                                                 plural=USERS_PLURAL, name=username)
    except ApiException as exe:
        if exe.status == 404:
            logger.debug(f"User {username} not found")
            return None
        raise exe

    return User.from_k8s_response_dict(user_data)
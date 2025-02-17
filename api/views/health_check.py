# Copyright The IETF Trust 2020, All Rights Reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

__author__ = 'Slavomir Mazur'
__copyright__ = 'Copyright The IETF Trust 2020, All Rights Reserved'
__license__ = 'Apache License, Version 2.0'
__email__ = 'slavomir.mazur@pantheon.tech'

import json
import time
from logging import Logger

import requests
from flask.blueprints import Blueprint
from flask.helpers import make_response
from flask.json import jsonify

import utility.log as log
from api.my_flask import app
from jobs.celery import test_task
from jobs.jobs_information import get_response
from jobs.status_messages import StatusMessage
from utility.staticVariables import json_headers


class HealthcheckBlueprint(Blueprint):
    logger: Logger


bp = HealthcheckBlueprint('healthcheck', __name__)


@bp.record
def init_logger(state):
    bp.logger = log.get_logger('healthcheck', '{}/healthcheck.log'.format(state.app.config.d_logs))


@bp.before_request
def set_config():
    global app_config, users
    app_config = app.config
    users = app_config.redis_users


@bp.route('/services-list', methods=['GET'])
def get_services_list():
    response_body = []
    service_endpoints = [
        'opensearch',
        'confd-admin',
        'redis-admin',
        'yang-search-admin',
        'yang-validator-admin',
        'yangre-admin',
        'nginx',
        'yangcatalog',
        'celery',
    ]
    service_names = [
        'OpenSearch',
        'ConfD',
        'Redis',
        'YANG search',
        'YANG validator',
        'YANGre',
        'NGINX',
        'YangCatalog',
        'Celery',
    ]
    for name, endpoint in zip(service_names, service_endpoints):
        pair = {'name': name, 'endpoint': endpoint}
        response_body.append(pair)
    return make_response(jsonify(response_body), 200)


@bp.route('/opensearch', methods=['GET'])
def health_check_opensearch():
    service_name = 'OpenSearch'
    try:
        # try to ping OpenSearch
        if app_config.opensearch_manager.ping():
            # get health of cluster
            health = app_config.opensearch_manager.cluster_health()
            health_status = health.get('status')
            # get list of indices
            indices = app_config.opensearch_manager.get_indices()
            if len(indices) > 0:
                return make_response(
                    jsonify(
                        {
                            'info': 'OpenSearch is running',
                            'status': 'running',
                            'message': 'Cluster status: {}'.format(health_status),
                        },
                    ),
                    200,
                )
            else:
                return make_response(
                    jsonify(
                        {
                            'info': 'OpenSearch is running',
                            'status': 'problem',
                            'message': 'Cluster status: {} Number of indices: {}'.format(health_status, len(indices)),
                        },
                    ),
                    200,
                )
        else:
            bp.logger.info('Cannot connect to OpenSearch database')
            return make_response(
                jsonify(
                    {
                        'info': 'Not OK - OpenSearch is not running',
                        'status': 'down',
                        'error': 'Cannot ping OpenSearch',
                    },
                ),
                200,
            )
    except Exception as err:
        bp.logger.error('Cannot connect to OpenSearch database. Error: {}'.format(err))
        return make_response(jsonify(error_response(service_name, err)), 200)


@bp.route('/confd', methods=['GET'])
def health_check_confd():
    service_name = 'ConfD'

    try:
        # Check if ConfD is running
        response = app.confdService.get_restconf()

        if response.status_code == 200:
            bp.logger.info('yang-catalog:catalog is running on ConfD')
            response = {'info': 'Success'}
        else:
            bp.logger.error('yang-catalog:catalog is NOT running on ConfD')
            response = {'error': 'Unable to ping yang-catalog:catalog'}
        return (response, 200)

    except Exception as err:
        bp.logger.error('Cannot ping {}. Error: {}'.format(service_name, err))
        return make_response(jsonify(error_response(service_name, err)), 200)


@bp.route('/redis', methods=['GET'])
def health_check_redis():
    try:
        result = app_config.redis.ping()
        if result:
            response = {'info': 'Success'}
        else:
            bp.logger.error('Redis ping failed to respond')
            response = {'error': 'Unable to ping Redis'}
        return response, 200

    except Exception:
        bp.logger.exception('Cannot ping Redis')
        error_message = {'error': 'Unable to ping Redis'}
        return error_message, 200


@bp.route('/nginx', methods=['GET'])
def health_check_nginx():
    service_name = 'NGINX'
    try:
        response = requests.get('{}/nginx-health'.format(app_config.w_my_uri), headers=json_headers)
        bp.logger.info('NGINX responded with a code {}'.format(response.status_code))
        response_message = response.json()['info']
        if response.status_code == 200 and response_message == 'Success':
            return make_response(
                jsonify(
                    {
                        'info': 'NGINX is available',
                        'status': 'running',
                        'message': 'NGINX responded with a code {}'.format(response.status_code),
                    },
                ),
                200,
            )
        else:
            return make_response(
                jsonify(
                    {
                        'info': 'Not OK - NGINX is not available',
                        'status': 'problem',
                        'message': 'NGINX responded with a code {}'.format(response.status_code),
                    },
                ),
                200,
            )
    except Exception as err:
        bp.logger.error('Cannot ping {}. Error: {}'.format(service_name, err))
        return make_response(jsonify(error_response(service_name, err)), 200)


@bp.route('/yangre-admin', methods=['GET'])
def health_check_yangre_admin():
    service_name = 'yangre'
    yangre_prefix = '{}/yangre'.format(app_config.w_my_uri)

    pattern = '[0-9]*'
    content = '123456789'
    body = json.dumps({'pattern': pattern, 'content': content, 'inverted': False, 'pattern_nb': '1'})
    try:
        response = requests.post('{}/v1/yangre'.format(yangre_prefix), data=body, headers=json_headers)
        bp.logger.info('yangre responded with a code {}'.format(response.status_code))
        if response.status_code == 200:
            response_message = response.json()
            if response_message['yangre_output'] == '':
                return make_response(
                    jsonify(
                        {
                            'info': '{} is available'.format(service_name),
                            'status': 'running',
                            'message': 'yangre successfully validated string',
                        },
                    ),
                    200,
                )
            else:
                return make_response(
                    jsonify(
                        {
                            'info': '{} is available'.format(service_name),
                            'status': 'problem',
                            'message': response_message['yangre_output'],
                        },
                    ),
                    200,
                )
        elif response.status_code == 400 or response.status_code == 404:
            return make_response(
                jsonify(
                    {
                        'info': '{} is available'.format(service_name),
                        'status': 'problem',
                        'message': 'yangre responded with a code {}'.format(response.status_code),
                    },
                ),
                200,
            )
        else:
            err = 'yangre responded with a code {}'.format(response.status_code)
            return make_response(jsonify(error_response(service_name, err)), 200)
    except Exception as err:
        bp.logger.error('Cannot ping {}. Error: {}'.format(service_name, err))
        return make_response(jsonify(error_response(service_name, err)), 200)


@bp.route('/yang-validator-admin', methods=['GET'])
def health_check_yang_validator_admin():
    service_name = 'yang-validator'
    yang_validator_prefix = '{}/yangvalidator'.format(app_config.w_my_uri)

    rfc_number = '7223'
    body = json.dumps({'rfc': rfc_number, 'latest': True})
    try:
        response = requests.post('{}/v2/rfc'.format(yang_validator_prefix), data=body, headers=json_headers)
        bp.logger.info('yang-validator responded with a code {}'.format(response.status_code))
        if response.status_code == 200:
            response_message = response.json()
            if response_message:
                return make_response(
                    jsonify(
                        {
                            'info': '{} is available'.format(service_name),
                            'status': 'running',
                            'message': '{} successfully fetched and validated RFC{}'.format(service_name, rfc_number),
                        },
                    ),
                    200,
                )
            else:
                return make_response(
                    jsonify(
                        {
                            'info': '{} is available'.format(service_name),
                            'status': 'problem',
                            'message': 'RFC{} responded with empty body'.format(rfc_number),
                        },
                    ),
                    200,
                )
        elif response.status_code == 400 or response.status_code == 404:
            return make_response(
                jsonify(
                    {
                        'info': '{} is available'.format(service_name),
                        'status': 'problem',
                        'message': '{} responded with a code {}'.format(service_name, response.status_code),
                    },
                ),
                200,
            )
        else:
            err = '{} responded with a code {}'.format(service_name, response.status_code)
            return make_response(jsonify(error_response(service_name, err)), 200)
    except Exception as err:
        bp.logger.error('Cannot ping {}. Error: {}'.format(service_name, err))
        return make_response(jsonify(error_response(service_name, err)), 200)


@bp.route('/yang-search-admin', methods=['GET'])
def health_check_yang_search_admin():
    service_name = 'yang-search'
    yang_search_prefix = '{}/search'.format(app_config.w_yangcatalog_api_prefix)
    module_name = 'yang-catalog,2018-04-03,ietf'
    try:
        response = requests.get('{}/modules/{}'.format(yang_search_prefix, module_name), headers=json_headers)
        bp.logger.info('yang-search responded with a code {}'.format(response.status_code))
        if response.status_code == 200:
            response_message = response.json()
            if response_message['module'] and len(response_message['module']) > 0:
                return make_response(
                    jsonify(
                        {
                            'info': '{} is available'.format(service_name),
                            'status': 'running',
                            'message': '{} module successfully found'.format(module_name),
                        },
                    ),
                    200,
                )
            else:
                return make_response(
                    jsonify(
                        {
                            'info': '{} is available'.format(service_name),
                            'status': 'problem',
                            'message': 'Module {} not found'.format(module_name),
                        },
                    ),
                    200,
                )
        elif response.status_code == 400 or response.status_code == 404:
            err = json.loads(response.text).get('error')
            return make_response(
                jsonify(
                    {
                        'info': '{} is available'.format(service_name),
                        'status': 'problem',
                        'message': '{} responded with a message: {}'.format(service_name, err),
                    },
                ),
                200,
            )
        else:
            err = '{} responded with a code {}'.format(service_name, response.status_code)
            return make_response(jsonify(error_response(service_name, err)), 200)
    except Exception as err:
        bp.logger.error('Cannot ping {}. Error: {}'.format(service_name, err))
        return make_response(jsonify(error_response(service_name, err)), 200)


@bp.route('/confd-admin', methods=['GET'])
def health_check_confd_admin():
    service_name = 'ConfD'

    try:
        # Check if ConfD is running
        response = app.confdService.get_restconf()

        if response.status_code == 200:
            bp.logger.info('ConfD is running')
            # Check if ConfD is filled with data
            mod_key = 'yang-catalog,2018-04-03,ietf'
            response = app.confdService.get_module(mod_key)

            bp.logger.info('Status code {} while getting data of {} module'.format(response.status_code, mod_key))
            if response.status_code != 200 and response.status_code != 201 and response.status_code != 204:
                response = {
                    'info': 'Not OK - ConfD is not filled',
                    'status': 'problem',
                    'message': 'Cannot get data of yang-catalog:modules',
                }
                return make_response(jsonify(response), 200)
            else:
                module_data = response.json()
                num_of_modules = len(module_data['yang-catalog:module'])
                bp.logger.info('{} module successfully loaded from ConfD'.format(mod_key))
                if num_of_modules > 0:
                    return make_response(
                        jsonify(
                            {
                                'info': 'ConfD is running',
                                'status': 'running',
                                'message': '{} successfully loaded from ConfD'.format(mod_key),
                            },
                        ),
                        200,
                    )
                else:
                    return make_response(
                        jsonify(
                            {
                                'info': 'ConfD is running',
                                'status': 'problem',
                                'message': 'ConfD is running but no modules loaded',
                            },
                        ),
                        200,
                    )
        else:
            bp.logger.info('Cannot get data from ConfD')
            err = 'Cannot get data from ConfD'
            return make_response(jsonify(error_response(service_name, err)), 200)
    except Exception as err:
        bp.logger.error('Cannot ping {}. Error: {}'.format(service_name, err))
        return make_response(jsonify(error_response(service_name, err)), 200)


@bp.route('/redis-admin', methods=['GET'])
def health_check_redis_admin():
    service_name = 'Redis'

    try:
        redis_key = 'yang-catalog@2018-04-03/ietf'
        result = app.redisConnection.get_module(redis_key)
        if result == '{}':
            response = {
                'info': 'Not OK - Redis is not filled',
                'status': 'problem',
                'message': 'Cannot get yang-catalog@2018-04-03/ietf',
            }
        else:
            bp.logger.info('{} module successfully loaded from Redis'.format(redis_key))
            response = {
                'info': 'Redis is running',
                'status': 'running',
                'message': '{} successfully loaded from Redis'.format(redis_key),
            }

    except Exception as err:
        bp.logger.error('Cannot ping Redis. Error: {}'.format(err))
        return error_response(service_name, err)

    return response


@bp.route('/yangcatalog', methods=['GET'])
def health_check_yangcatalog():
    service_name = 'yangcatalog'
    status = 'running'
    message = 'All URLs responded with status code 200'
    additional_info = []

    urls = [
        {'url': 'http://yangcatalog.org', 'verify': True},
        {'url': 'http://www.yangcatalog.org', 'verify': True},
        {'url': 'https://yangcatalog.org', 'verify': True},
        {'url': 'https://www.yangcatalog.org', 'verify': True},
        {'url': 'http://yangvalidator.com', 'verify': True},
        {'url': 'http://www.yangvalidator.com', 'verify': True},
        {'url': 'https://yangvalidator.com', 'verify': True},
        {'url': 'https://www.yangvalidator.com', 'verify': True},
        {'url': 'http://18.224.127.129', 'verify': False},
        {'url': 'https://18.224.127.129', 'verify': False},
        {'url': 'http://[2600:1f16:ba:200:a10d:3212:e763:e720]', 'verify': False},
        {'url': 'https://[2600:1f16:ba:200:a10d:3212:e763:e720]', 'verify': False},
    ]

    for item in urls:
        url = item.get('url', '')
        result = {'label': url}
        try:
            response = requests.get(url, verify=item.get('verify', True))
            status_code = response.status_code
            bp.logger.info('URl: {} Status code: {}'.format(url, status_code))
            result['message'] = '{} OK'.format(status_code)
        except Exception:
            result['message'] = '500 NOT OK'
            status = 'problem'
            message = 'Problem occured, see additional info'
        additional_info.append(result)

    return make_response(
        jsonify(
            {
                'info': '{} is available'.format(service_name),
                'status': status,
                'message': message,
                'additional_info': additional_info,
            },
        ),
        200,
    )


@bp.route('/cronjobs', methods=['GET'])
def check_cronjobs():
    try:
        with open('{}/cronjob.json'.format(app_config.d_temp), 'r') as f:
            file_content = json.load(f)
    except (FileNotFoundError, json.decoder.JSONDecodeError):
        bp.logger.error('cronjob.json file does not exist')
        file_content = {}
    return make_response(jsonify({'data': file_content}), 200)


@bp.route('/celery', methods=['GET'])
def health_check_celery():
    result = test_task.s('test', 1).apply_async()
    attempts = 3
    status = StatusMessage.IN_PROGRESS.value
    reason = ''
    while attempts > 0:
        status, reason = get_response(app_config.celery_app, result.id)
        if status == StatusMessage.IN_PROGRESS:
            time.sleep(5)
            attempts -= 1
            continue
        break
    message_mapping = {
        StatusMessage.IN_PROGRESS.value: (
            'Waiting for the finish of the test task but only one task can be run at a time, so it\'s possible that '
            'another long-running task is being executed'
        ),
        StatusMessage.SUCCESS.value: f'Test task finished successfully with such message: {reason}',
        StatusMessage.FAIL.value: f'Test task failed with such traceback: {reason}',
    }
    return make_response(
        jsonify(
            {
                'info': 'Celery is available',
                'status': 'running' if status == StatusMessage.SUCCESS else 'problem',
                'message': message_mapping.get(status),
            },
        ),
        200,
    )


def error_response(service_name, err):
    return {
        'info': 'Not OK - {} is not available'.format(service_name),
        'status': 'down',
        'error': 'Cannot ping {}. Error: {}'.format(service_name, err),
    }

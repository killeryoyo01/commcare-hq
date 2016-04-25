from corehq.apps.change_feed.consumer.feed import KafkaChangeFeed
from corehq.apps.change_feed.document_types import COMMCARE_USER, WEB_USER, FORM
from corehq.apps.change_feed.topics import FORM_SQL
from corehq.apps.users.models import CommCareUser, CouchUser
from corehq.apps.users.util import WEIRD_USER_IDS
from corehq.elastic import (
    doc_exists_in_es,
    send_to_elasticsearch, get_es_new, ES_META
)
from corehq.pillows.mappings.user_mapping import USER_MAPPING, USER_INDEX, USER_META, USER_INDEX_INFO
from corehq.util.quickcache import quickcache
from pillowtop.checkpoints.manager import PillowCheckpoint, PillowCheckpointEventHandler
from pillowtop.listener import AliasedElasticPillow
from pillowtop.pillow.interface import ConstructedPillow
from pillowtop.processors import ElasticProcessor, PillowProcessor
from pillowtop.reindexer.change_providers.couch import CouchViewChangeProvider
from pillowtop.reindexer.reindexer import ElasticPillowReindexer


class UserPillow(AliasedElasticPillow):
    """
    Simple/Common Case properties Indexer
    """

    document_class = CommCareUser   # while this index includes all users,
                                    # I assume we don't care about querying on properties specific to WebUsers
    couch_filter = "users/all_users"
    es_timeout = 60
    es_alias = "hqusers"
    es_type = "user"
    es_meta = USER_META
    es_index = USER_INDEX
    default_mapping = USER_MAPPING

    @classmethod
    def get_unique_id(self):
        return USER_INDEX


def update_unknown_user_from_form_if_necessary(es, doc_dict):
    doc = doc_dict
    user_id, username, domain, xform_id = _get_user_fields_from_form_doc(doc)

    if user_id in WEIRD_USER_IDS:
        user_id = None

    if (user_id and not _user_exists(user_id)
            and not doc_exists_in_es('users', user_id)):
        doc_type = "AdminUser" if username == "admin" else "UnknownUser"
        doc = {
            "_id": user_id,
            "domain": domain,
            "username": username,
            "first_form_found_in": xform_id,
            "doc_type": doc_type,
        }
        if domain:
            doc["domain_membership"] = {"domain": domain}
        es.create(USER_INDEX, ES_META['users'].type, body=doc, id=user_id)


@quickcache(['user_id'])
def _user_exists(user_id):
    return CouchUser.get_db().doc_exist(user_id)


def _get_user_fields_from_form_doc(form_doc):
    form_meta = form_doc.get('form', {}).get('meta', {})
    domain = form_doc.get('domain')
    user_id = form_meta.get('userID')
    username = form_meta.get('username')
    xform_id = form_doc.get('_id')
    return user_id, username, domain, xform_id


class UnknownUsersProcessor(PillowProcessor):
    def __init__(self):
        self._es = get_es_new()

    def process_change(self, pillow_instance, change, do_set_checkpoint):
        update_unknown_user_from_form_if_necessary(self._es, change.get_document())


def get_unknown_users_pillow(pillow_id='unknown-users-pillow'):
    """
    This pillow adds users from xform submissions that come in to the User Index if they don't exist in HQ
    """
    checkpoint = PillowCheckpoint(
        pillow_id,
    )
    processor = UnknownUsersProcessor()
    return ConstructedPillow(
        name=pillow_id,
        checkpoint=checkpoint,
        change_feed=KafkaChangeFeed(topics=[FORM, FORM_SQL], group_id='unknown-users'),
        processor=processor,
        change_processed_event_handler=PillowCheckpointEventHandler(
            checkpoint=checkpoint, checkpoint_frequency=100,
        ),
    )


def add_demo_user_to_user_index():
    send_to_elasticsearch(
        'users',
        {"_id": "demo_user", "username": "demo_user", "doc_type": "DemoUser"}
    )


def get_user_kafka_to_elasticsearch_pillow(pillow_id='UserPillow'):
    checkpoint = PillowCheckpoint(
        pillow_id,
    )
    domain_processor = ElasticProcessor(
        elasticsearch=get_es_new(),
        index_info=USER_INDEX_INFO,
    )
    return ConstructedPillow(
        name=pillow_id,
        checkpoint=checkpoint,
        change_feed=KafkaChangeFeed(topics=[COMMCARE_USER, WEB_USER], group_id='users-to-es'),
        processor=domain_processor,
        change_processed_event_handler=PillowCheckpointEventHandler(
            checkpoint=checkpoint, checkpoint_frequency=100,
        ),
    )


def get_user_reindexer():
    return ElasticPillowReindexer(
        pillow=get_user_kafka_to_elasticsearch_pillow(),
        change_provider=CouchViewChangeProvider(
            couch_db=CommCareUser.get_db(),
            view_name='users/by_username',
            view_kwargs={
                'include_docs': True,
            }
        ),
        elasticsearch=get_es_new(),
        index_info=USER_INDEX_INFO,
    )

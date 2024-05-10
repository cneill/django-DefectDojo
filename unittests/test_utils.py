import logging
from contextlib import contextmanager
from unittest.mock import Mock, patch

from dojo.authorization.roles_permissions import Roles
from dojo.models import (
    IMPORT_CLOSED_FINDING,
    IMPORT_CREATED_FINDING,
    IMPORT_REACTIVATED_FINDING,
    IMPORT_UNTOUCHED_FINDING,
    Dojo_Group,
    Dojo_Group_Member,
    Dojo_User,
    Endpoint,
    Engagement,
    Finding,
    Notifications,
    Product,
    Product_Type,
    Role,
    System_Settings,
    Test,
    Test_Import,
    Test_Import_Finding_Action,
)
from dojo.utils import (
    create_bleached_link,
    dojo_crypto_encrypt,
    get_product,
    is_safe_url,
    prepare_for_view,
    truncate_with_dots,
    user_post_save,
)

from .dojo_test_case import DojoTestCase

logger = logging.getLogger(__name__)

TEST_IMPORT_ALL = Test_Import.objects.all()
TEST_IMPORTS = Test_Import.objects.filter(type=Test_Import.IMPORT_TYPE)
TEST_REIMPORTS = Test_Import.objects.filter(type=Test_Import.REIMPORT_TYPE)
TEST_IMPORT_FINDING_ACTION_ALL = Test_Import_Finding_Action.objects.all()
TEST_IMPORT_FINDING_ACTION_AFFECTED = TEST_IMPORT_FINDING_ACTION_ALL.filter(
    action__in=[IMPORT_CREATED_FINDING, IMPORT_CLOSED_FINDING, IMPORT_REACTIVATED_FINDING])
TEST_IMPORT_FINDING_ACTION_CREATED = TEST_IMPORT_FINDING_ACTION_ALL.filter(action=IMPORT_CREATED_FINDING)
TEST_IMPORT_FINDING_ACTION_CLOSED = TEST_IMPORT_FINDING_ACTION_ALL.filter(action=IMPORT_CLOSED_FINDING)
TEST_IMPORT_FINDING_ACTION_REACTIVATED = TEST_IMPORT_FINDING_ACTION_ALL.filter(action=IMPORT_REACTIVATED_FINDING)
TEST_IMPORT_FINDING_ACTION_UNTOUCHED = TEST_IMPORT_FINDING_ACTION_ALL.filter(action=IMPORT_UNTOUCHED_FINDING)

TESTS = Test.objects.all()
ENGAGEMENTS = Engagement.objects.all()
PRODUCTS = Product.objects.all()
PRODUCT_TYPES = Product_Type.objects.all()
ENDPOINTS = Endpoint.objects.all()


class TestUtils(DojoTestCase):
    def test_encryption(self):
        test_input = "Hello World!"
        encrypt = dojo_crypto_encrypt(test_input)
        test_output = prepare_for_view(encrypt)
        self.assertEqual(test_input, test_output)

    def test_create_bleached_link(self):
        # url, title, expected
        unsafe_cases = [
            (
                '"><script>alert(1)</script>',
                "test",
                '<a href="">&lt;script&gt;alert(1)&lt;/script&gt;" target="_blank" title="test"&gt;test</a>',
            ),
            ('" onclick=alert(1)>', "test", '<a href="">" target="_blank" title="test"&gt;test</a>'),
        ]
        for i, unsafe in enumerate(unsafe_cases):
            with self.subTest(i):
                result = create_bleached_link(unsafe[0], unsafe[1])
                self.assertEqual(unsafe[2], result)

        # url, title, expected
        safe_cases = [
            ("https://myhost.com", "title", '<a href="https://myhost.com" target="_blank" title="title">title</a>'),
            ("/", "title", '<a href="/" target="_blank" title="title">title</a>'),
        ]
        for i, safe in enumerate(safe_cases):
            with self.subTest(len(unsafe_cases) + i):
                result = create_bleached_link(safe[0], safe[1])
                self.assertEqual(safe[2], result)

    def test_is_safe_url(self):
        # Because allowed_hosts=None only paths are allowed - no hosts, no schemes, etc.
        unsafe_cases = [
            "",
            "ftp://myhost.com",
            "ssh://myhost.com",
            "///myhost.com",
            "https://localhost/path",
        ]
        for i, unsafe in enumerate(unsafe_cases):
            with self.subTest(i):
                self.assertFalse(is_safe_url(unsafe))

        safe_cases = [
            "/",
            "/some/path",
        ]
        for i, safe in enumerate(safe_cases):
            with self.subTest(len(unsafe_cases) + i):
                self.assertTrue(is_safe_url(safe))

    def test_truncate_with_dots(self):
        # Expected string, provided string, length
        test_cases = [
            ("", "", 5),
            ("test", "test", 4),
            ("test...", "test_longer", 7),
            ("test", "test", 500),
        ]
        for i, test_case in enumerate(test_cases):
            with self.subTest(i):
                result = truncate_with_dots(test_case[1], test_case[2])
                self.assertLessEqual(len(result), test_case[2])
                self.assertEqual(test_case[0], result)

        # Ensure that we can't pass a value < 3 since this doesn't make any sense
        with self.subTest(len(test_cases)):
            with self.assertRaises(ValueError):
                truncate_with_dots("test", 2)

    def test_get_product(self):
        product = Product()
        engagement = Engagement(
            product=product,
        )
        test = Test(
            engagement=engagement,
        )
        finding = Finding(
            test=test,
        )
        self.assertEqual(None, get_product(None))
        self.assertEqual(product, get_product(finding))
        self.assertEqual(product, get_product(test))
        self.assertEqual(product, get_product(engagement))
        self.assertEqual(product, get_product(product))
        with self.assertRaises(TypeError):
            get_product({"not": "valid"})

        with self.assertRaises(Test.DoesNotExist):
            get_product(Finding())

        with self.assertRaises(Engagement.DoesNotExist):
            get_product(Test())

        with self.assertRaises(Product.DoesNotExist):
            get_product(Engagement())

    @patch('dojo.models.System_Settings.objects')
    @patch('dojo.utils.Dojo_Group_Member')
    @patch('dojo.utils.Notifications')
    def test_user_post_save_without_template(self, mock_notifications, mock_member, mock_settings):
        user = Dojo_User()
        user.id = 1

        group = Dojo_Group()
        group.id = 1

        role = Role.objects.get(id=Roles.Reader)

        system_settings_group = System_Settings()
        system_settings_group.default_group = group
        system_settings_group.default_group_role = role

        mock_settings.get.return_value = system_settings_group
        save_mock_member = Mock(return_value=Dojo_Group_Member())
        mock_member.return_value = save_mock_member

        save_mock_notifications = Mock(return_value=Notifications())
        mock_notifications.return_value = save_mock_notifications
        mock_notifications.objects.get.side_effect = Exception("Mock no templates")

        user_post_save(None, user, True)

        mock_member.assert_called_with(group=group, user=user, role=role)
        save_mock_member.save.assert_called_once()

        mock_notifications.assert_called_with(user=user)
        save_mock_notifications.save.assert_called_once()

    @patch('dojo.models.System_Settings.objects')
    @patch('dojo.utils.Dojo_Group_Member')
    @patch('dojo.utils.Notifications')
    def test_user_post_save_with_template(self, mock_notifications, mock_member, mock_settings):
        user = Dojo_User()
        user.id = 1

        group = Dojo_Group()
        group.id = 1

        template = Mock(Notifications(template=False, user=user))

        role = Role.objects.get(id=Roles.Reader)

        system_settings_group = System_Settings()
        system_settings_group.default_group = group
        system_settings_group.default_group_role = role

        mock_settings.get.return_value = system_settings_group
        save_mock_member = Mock(return_value=Dojo_Group_Member())
        mock_member.return_value = save_mock_member

        mock_notifications.objects.get.return_value = template

        user_post_save(None, user, True)

        mock_member.assert_called_with(group=group, user=user, role=role)
        save_mock_member.save.assert_called_once()

        mock_notifications.objects.get.assert_called_with(template=True)
        template.save.assert_called_once()

    @patch('dojo.models.System_Settings.objects')
    @patch('dojo.utils.Dojo_Group_Member')
    @patch('dojo.utils.Notifications')
    def test_user_post_save_email_pattern_matches(self, mock_notifications, mock_member, mock_settings):
        user = Dojo_User()
        user.id = 1
        user.email = 'john.doe@example.com'

        group = Dojo_Group()
        group.id = 1

        role = Role.objects.get(id=Roles.Reader)

        system_settings_group = System_Settings()
        system_settings_group.default_group = group
        system_settings_group.default_group_role = role
        system_settings_group.default_group_email_pattern = '.*@example.com'

        mock_settings.get.return_value = system_settings_group
        save_mock_member = Mock(return_value=Dojo_Group_Member())
        mock_member.return_value = save_mock_member
        save_mock_notifications = Mock(return_value=Notifications())
        mock_notifications.return_value = save_mock_notifications
        mock_notifications.objects.get.side_effect = Exception("Mock no templates")

        user_post_save(None, user, True)

        mock_member.assert_called_with(group=group, user=user, role=role)
        save_mock_member.save.assert_called_once()

    @patch('dojo.models.System_Settings.objects')
    @patch('dojo.utils.Dojo_Group_Member')
    @patch('dojo.utils.Notifications')
    def test_user_post_save_email_pattern_does_not_match(self, mock_notifications, mock_member, mock_settings):
        user = Dojo_User()
        user.id = 1
        user.email = 'john.doe@partner.example.com'

        group = Dojo_Group()
        group.id = 1

        role = Role.objects.get(id=Roles.Reader)

        system_settings_group = System_Settings()
        system_settings_group.default_group = group
        system_settings_group.default_group_role = role
        system_settings_group.default_group_email_pattern = '.*@example.com'
        save_mock_notifications = Mock(return_value=Notifications())
        mock_notifications.return_value = save_mock_notifications
        mock_notifications.objects.get.side_effect = Exception("Mock no templates")

        mock_settings.get.return_value = system_settings_group
        save_mock_member = Mock(return_value=Dojo_Group_Member())
        mock_member.return_value = save_mock_member

        user_post_save(None, user, True)

        mock_member.assert_not_called()
        save_mock_member.save.assert_not_called()


class assertNumOfModelsCreated:
    def __init__(self, test_case, queryset, num):
        self.test_case = test_case
        self.queryset = queryset
        self.num = num

    def __enter__(self):
        self.initial_model_count = self.queryset.count()
        # logger.debug('initial model count for %s: %i', self.queryset.query, self.initial_model_count)
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.final_model_count = self.queryset.count()
        # logger.debug('final model count for %s: %i', self.queryset.query, self.final_model_count)
        created_count = self.final_model_count - self.initial_model_count
        self.test_case.assertEqual(
            created_count, self.num,
            "%i %s objects created, %i expected. query: %s, first 100 objects: %s" % (
                created_count, self.queryset.model, self.num, self.queryset.query, self.queryset.all().order_by('-id')[:100]
            )
        )


@contextmanager
def assertTestImportModelsCreated(test_case, imports=0, reimports=0, affected_findings=0,
                                    created=0, closed=0, reactivated=0, untouched=0):

    with assertNumOfModelsCreated(test_case, TEST_IMPORTS, num=imports) as ti_import_count, \
            assertNumOfModelsCreated(test_case, TEST_REIMPORTS, num=reimports) as ti_reimport_count, \
            assertNumOfModelsCreated(test_case, TEST_IMPORT_FINDING_ACTION_AFFECTED, num=affected_findings) as tifa_count, \
            assertNumOfModelsCreated(test_case, TEST_IMPORT_FINDING_ACTION_CREATED, num=created) as tifa_created_count, \
            assertNumOfModelsCreated(test_case, TEST_IMPORT_FINDING_ACTION_CLOSED, num=closed) as tifa_closed_count, \
            assertNumOfModelsCreated(test_case, TEST_IMPORT_FINDING_ACTION_REACTIVATED, num=reactivated) as tifa_reactivated_count, \
            assertNumOfModelsCreated(test_case, TEST_IMPORT_FINDING_ACTION_UNTOUCHED, num=untouched) as tifa_untouched_count:

        yield (
                ti_import_count,
                ti_reimport_count,
                tifa_count,
                tifa_created_count,
                tifa_closed_count,
                tifa_reactivated_count,
                tifa_untouched_count
              )


@contextmanager
def assertImportModelsCreated(test_case, tests=0, engagements=0, products=0, product_types=0, endpoints=0):

    with assertNumOfModelsCreated(test_case, TESTS, num=tests) as test_count, \
            assertNumOfModelsCreated(test_case, ENGAGEMENTS, num=engagements) as engagement_count, \
            assertNumOfModelsCreated(test_case, PRODUCTS, num=products) as product_count, \
            assertNumOfModelsCreated(test_case, PRODUCT_TYPES, num=product_types) as product_type_count, \
            assertNumOfModelsCreated(test_case, ENDPOINTS, num=endpoints) as endpoint_count:

        yield (
                test_count,
                engagement_count,
                product_count,
                product_type_count,
                endpoint_count,
              )

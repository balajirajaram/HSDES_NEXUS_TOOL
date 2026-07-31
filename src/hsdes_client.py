"""HSDES REST API Comprehensive Client.

This module provides a comprehensive Python client for interacting with the Intel HSDES REST API.
Based on the official Swagger specification at https://hsdes.intel.com/rest/swagger.json

:author: Jeff Breazile
:version: 1.0.0
:date: 2025-01-17

This client covers all major HSDES API endpoints including:
- Article operations (CRUD, bulk operations, history, cloning)
- Query operations (execute, create, update, delete)
- Binary/Attachment management
- Article links and relationships
- User management
- Baseline operations
- BOM (Bill of Materials) operations
- Trace/E-Cypher operations
- Viewport operations
- Similarity analysis
- Magazine operations
- Token management

Example Usage:
    >>> from sharedlib.hsdes_comprehensive_client import HSDESComprehensiveClient
    >>> client = HSDESComprehensiveClient()
    >>> article = client.get_article(article_id=13014003631)
    >>> print(article['data'][0]['title'])
"""

import os
import tempfile
from typing import Any

import certifi
import requests
from requests_kerberos import OPTIONAL, HTTPKerberosAuth

try:
    # truststore makes Python's ssl module verify against the OS-native
    # certificate store (Windows Certificate Store / macOS Keychain / Linux
    # system trust) instead of the bundled certifi CA list. This is required
    # on corp machines behind a TLS-inspecting proxy: the proxy's root CA is
    # trusted by the OS (installed via Group Policy) but is NOT present in
    # certifi's bundle, so certifi-only verification fails with
    # "self-signed certificate in certificate chain" even though the OS
    # trusts the connection fine.
    import truststore

    truststore.inject_into_ssl()
    _TRUSTSTORE_AVAILABLE = True
except ImportError:
    _TRUSTSTORE_AVAILABLE = False


class HSDESComprehensiveClient:
    """Comprehensive client for Intel HSDES REST API supporting all documented endpoints.

    This class provides Python methods for all HSDES REST API operations as documented
    in the Swagger specification. It handles Kerberos authentication, SSL certificates,
    and request/response formatting.

    Attributes:
        base_url (str): Base URL for the HSDES API
        auth (HTTPKerberosAuth): Kerberos authentication handler
        session (requests.Session): HTTP session with configured SSL certificates
        ca_bundle_path (bool | str): `True` if verifying via the OS trust store
            (via `truststore`), otherwise a path to a CA certificate bundle

    Example:
        >>> client = HSDESComprehensiveClient()
        >>> article = client.get_article(13014003631, fields='id,title,description,status')
    """

    def __init__(self, base_url: str = "https://hsdes-api.intel.com/rest"):
        """Initialize the HSDES client with authentication and SSL configuration.

        Args:
            base_url (str): The base URL for the HSDES REST API.
                          Defaults to https://hsdes-api.intel.com/rest
        """
        self.base_url = base_url
        self.auth = HTTPKerberosAuth(mutual_authentication=OPTIONAL)
        self.ca_bundle_path = self._setup_ca_bundle()

        # Create a session for connection pooling
        self.session = requests.Session()
        self.session.auth = self.auth
        self.session.verify = self.ca_bundle_path
        self.session.headers.update({
            "Content-Type": "application/json",
            "APP": "hsdes-python-client"
        })

    def _setup_ca_bundle(self) -> bool | str:
        """Set up CA bundle with Intel internal certificates.

        Preferred path: if `truststore` is available, `ssl.SSLContext` has already
        been patched (see module import) to verify against the OS-native certificate
        store, which trusts Intel's TLS-inspecting proxy CA out of the box. In that
        case `requests.Session.verify` should simply be `True`.

        Fallback path (no truststore installed): attempt to combine certifi's bundle
        with an Intel-internal CA file from a corp file share. This path is legacy
        and depends on a share location that may not exist for all users/environments
        - if it's missing, we silently fall back to certifi only, which will fail
        SSL verification behind a TLS-inspecting proxy. Installing `truststore`
        (`pip install truststore`) is the robust fix.
        """
        if _TRUSTSTORE_AVAILABLE:
            return True

        intel_certs_path = (
            "\\\\amr.corp.intel.com\\ec\\proj\\ha\\sighting\\share\\hsdes_2.0\\"
            "Tools\\OpenSource_py\\certs\\20240813-Intel_certs\\pem_files\\"
            "Intel_Combined_All.pem"
        )

        ca_bundle = certifi.where()

        if os.path.exists(intel_certs_path):
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.pem') as temp_bundle:
                with open(ca_bundle) as default_certs:
                    temp_bundle.write(default_certs.read())

                with open(intel_certs_path) as intel_certs:
                    temp_bundle.write('\n')
                    temp_bundle.write(intel_certs.read())

                return temp_bundle.name
        else:
            return ca_bundle

    # ==================== Article Operations ====================

    def get_article(
        self,
        article_id: int,
        tenant: str | None = None,
        subject: str | None = None,
        fields: str = "id,title",
        rev: int | None = None
    ) -> dict[str, Any]:
        """Retrieve an article by ID.

        Args:
            article_id (int): Article ID
            tenant (Optional[str]): Tenant of the record
            subject (Optional[str]): Subject of the record
            fields (str): Comma-separated fields to retrieve
            rev (Optional[int]): Specific revision number

        Returns:
            Dict[str, Any]: Article data

        Example:
            >>> article = client.get_article(13014003631, fields='id,title,description,status')
        """
        url = f"{self.base_url}/article/{article_id}"
        params = {"fields": fields}
        if tenant:
            params["tenant"] = tenant
        if subject:
            params["subject"] = subject
        if rev is not None:
            params["rev"] = rev

        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def create_article(
        self,
        tenant: str,
        subject: str,
        field_values: list[dict[str, Any]],
        fetch: bool = False,
        debug: bool = False,
        utc_offset: str | None = None
    ) -> dict[str, Any]:
        """Create a new article.

        Args:
            tenant (str): Tenant for the article
            subject (str): Subject for the article
            field_values (List[Dict[str, Any]]): List of field-value dictionaries
            fetch (bool): Return created article data
            debug (bool): Validate only without creating
            utc_offset (Optional[str]): UTC offset for dates

        Returns:
            Dict[str, Any]: Created article response

        Example:
            >>> result = client.create_article(
            ...     tenant='server',
            ...     subject='bugeco',
            ...     field_values=[
            ...         {"title": "New Bug Report"},
            ...         {"description": "Detailed description"},
            ...         {"priority": "3-medium"}
            ...     ]
            ... )
        """
        url = f"{self.base_url}/article"
        body = {
            "tenant": tenant,
            "subject": subject,
            "fieldValues": field_values
        }

        params = {
            "fetch": str(fetch).lower(),
            "debug": str(debug).lower()
        }
        if utc_offset:
            params["utc_offset"] = utc_offset

        response = self.session.post(url, json=body, params=params)
        response.raise_for_status()
        return response.json()

    def update_article(
        self,
        article_id: int,
        field_values: list[dict[str, Any]],
        rev: int | None = None,
        fetch: bool = False,
        utc_offset: str | None = None,
        multi_select_append: bool = False,
        debug: bool = False
    ) -> dict[str, Any]:
        """Update an existing article.

        Note: fieldValues is a list of objects where order is important.

        Args:
            article_id (int): Article ID to update
            field_values (List[Dict[str, Any]]): List of field-value dictionaries
            rev (Optional[int]): Revision number for optimistic locking
            fetch (bool): Return updated article data
            utc_offset (Optional[str]): UTC offset
            multi_select_append (bool): Append to multi-select fields
            debug (bool): Validate only without updating

        Returns:
            Dict[str, Any]: Update response

        Example:
            >>> result = client.update_article(
            ...     article_id=13014003631,
            ...     field_values=[{"description": "Updated description"}],
            ...     fetch=True
            ... )
        """
        url = f"{self.base_url}/article/{article_id}"
        body = {"fieldValues": field_values}

        params = {
            "fetch": str(fetch).lower(),
            "debug": str(debug).lower(),
            "multi_select_append": str(multi_select_append).lower()
        }
        if rev is not None:
            params["rev"] = rev
        if utc_offset:
            params["utc_offset"] = utc_offset

        response = self.session.put(url, json=body, params=params)
        response.raise_for_status()
        return response.json()

    def get_article_history(
        self,
        article_id: int,
        tenant: str | None = None,
        subject: str | None = None,
        rev: int | None = None,
        fields: str = "id,title"
    ) -> dict[str, Any]:
        """Get revision history for an article.

        Args:
            article_id (int): Article ID
            tenant (Optional[str]): Tenant
            subject (Optional[str]): Subject
            rev (Optional[int]): Specific revision
            fields (str): Fields to return

        Returns:
            Dict[str, Any]: Article history
        """
        url = f"{self.base_url}/article/{article_id}/history"
        params = {"fields": fields}
        if tenant:
            params["tenant"] = tenant
        if subject:
            params["subject"] = subject
        if rev is not None:
            params["rev"] = rev

        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def get_article_base64(
        self,
        article_id: int,
        tenant: str | None = None,
        subject: str | None = None,
        rev: int | None = None,
        fields: str = "id,title"
    ) -> dict[str, Any]:
        """Get article with inline base64 encoded images.

        Image references will be replaced with inline base64 data.

        Args:
            article_id (int): Article ID
            tenant (Optional[str]): Tenant
            subject (Optional[str]): Subject
            rev (Optional[int]): Revision
            fields (str): Fields to return

        Returns:
            Dict[str, Any]: Article with base64 images
        """
        url = f"{self.base_url}/article/{article_id}/base64"
        params = {"fields": fields}
        if tenant:
            params["tenant"] = tenant
        if subject:
            params["subject"] = subject
        if rev is not None:
            params["rev"] = rev

        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def clone_article(
        self,
        article_id: int,
        dest_tenant: str | None = None,
        dest_subject: str | None = None,
        field_values: list[dict[str, Any]] | None = None,
        copy_attachment: bool = False,
        copy_comment: bool = False,
        sendmail: bool = False
    ) -> dict[str, Any]:
        """Clone an article.

        Args:
            article_id (int): Article ID to clone
            dest_tenant (Optional[str]): Destination tenant
            dest_subject (Optional[str]): Destination subject
            field_values (Optional[List[Dict]]): Field overrides
            copy_attachment (bool): Copy attachments
            copy_comment (bool): Copy comments
            sendmail (bool): Send notification

        Returns:
            Dict[str, Any]: Cloned article info
        """
        url = f"{self.base_url}/article/{article_id}/clone"
        body = {}
        if dest_tenant:
            body["destTenant"] = dest_tenant
        if dest_subject:
            body["destSubject"] = dest_subject
        if field_values:
            body["fieldValues"] = field_values
        body["copy_attachment"] = str(copy_attachment).lower()
        body["copy_comment"] = str(copy_comment).lower()
        body["sendmail"] = str(sendmail).lower()

        response = self.session.post(url, json=body)
        response.raise_for_status()
        return response.json()

    def bulk_create_articles(
        self,
        tenant: str,
        subject: str,
        articles: list[list[dict[str, Any]]],
        return_all_errors: bool = False,
        send_mail: bool = False
    ) -> dict[str, Any]:
        """Create multiple articles in one call.

        Args:
            tenant (str): Tenant
            subject (str): Subject
            articles (List[List[Dict]]): List of articles (each article is list of field-value dicts)
            return_all_errors (bool): Find all errors instead of stopping at first
            send_mail (bool): Send notifications

        Returns:
            Dict[str, Any]: Bulk creation results

        Example:
            >>> articles = [
            ...     [{"title": "Bug 1"}, {"owner": "user1"}],
            ...     [{"title": "Bug 2"}, {"owner": "user2"}]
            ... ]
            >>> result = client.bulk_create_articles('server', 'bugeco', articles)
        """
        url = f"{self.base_url}/article/bulk/{tenant}/{subject}"
        params = {
            "return_all_errors": str(return_all_errors).lower(),
            "send_mail": str(send_mail).lower()
        }

        response = self.session.post(url, json=articles, params=params)
        response.raise_for_status()
        return response.json()

    def bulk_update_articles(
        self,
        tenant: str,
        subject: str,
        articles: list[dict[str, Any]],
        fetch: bool = False,
        utc_offset: str | None = None
    ) -> dict[str, Any]:
        """Update multiple articles in one call.

        Args:
            tenant (str): Tenant
            subject (str): Subject
            articles (List[Dict]): List with id, rev, fieldValues for each article
            fetch (bool): Return updated data
            utc_offset (Optional[str]): UTC offset

        Returns:
            Dict[str, Any]: Bulk update results

        Example:
            >>> updates = [
            ...     {"id": 123, "rev": 1, "fieldValues": [{"status": "closed"}]},
            ...     {"id": 456, "rev": 2, "fieldValues": [{"status": "resolved"}]}
            ... ]
            >>> result = client.bulk_update_articles('server', 'bugeco', updates)
        """
        url = f"{self.base_url}/article/bulk/sync/{tenant}/{subject}"
        params = {"fetch": str(fetch).lower()}
        if utc_offset:
            params["utc_offset"] = utc_offset

        response = self.session.put(url, json=articles, params=params)
        response.raise_for_status()
        return response.json()

    def get_article_info(self, article_id: int) -> dict[str, Any]:
        """Get tenant/subject info for an article.

        Args:
            article_id (int): Article ID

        Returns:
            Dict[str, Any]: Article tenant/subject information
        """
        url = f"{self.base_url}/article/{article_id}/info"
        response = self.session.get(url)
        response.raise_for_status()
        return response.json()

    def get_article_children(
        self,
        article_id: int,
        tenant: str | None = None,
        child_subject: str = "comment",
        fields: str = "id,rev,owner,description"
    ) -> dict[str, Any]:
        """Get child records of an article (comments, attachments, etc).

        Args:
            article_id (int): Parent article ID
            tenant (Optional[str]): Tenant
            child_subject (str): Child subject (comment, ar, approval, attachment)
            fields (str): Fields to select

        Returns:
            Dict[str, Any]: Child records

        Example:
            >>> comments = client.get_article_children(
            ...     article_id=13014003631,
            ...     child_subject='comment'
            ... )
        """
        url = f"{self.base_url}/article/{article_id}/children"
        params = {
            "child_subject": child_subject,
            "fields": fields
        }
        if tenant:
            params["tenant"] = tenant

        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    # ==================== Article Links ====================

    def get_article_links(
        self,
        article_id: int,
        fields: str = "id,subject,tenant,title,owner,status,relationship",
        show_hidden: bool = False,
        show_deleted: bool = False
    ) -> dict[str, Any]:
        """Get related links/records for an article.

        Args:
            article_id (int): Article ID
            fields (str): Fields to return
            show_hidden (bool): Show hidden links
            show_deleted (bool): Show only deleted links

        Returns:
            Dict[str, Any]: Linked articles
        """
        url = f"{self.base_url}/article/{article_id}/links"
        params = {
            "fields": fields,
            "showHidden": "Y" if show_hidden else "N",
            "showDeleted": "Y" if show_deleted else "N"
        }

        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def add_article_link(self, source_id: int, target_id: int) -> dict[str, Any]:
        """Add a single link between articles.

        Args:
            source_id (int): Source article ID
            target_id (int): Target article ID

        Returns:
            Dict[str, Any]: Link operation result
        """
        url = f"{self.base_url}/article/{source_id}/links/{target_id}"
        response = self.session.post(url)
        response.raise_for_status()
        return response.json()

    def add_article_links_bulk(
        self,
        source_id: int,
        target_ids: list[int],
        link_type: str | None = None
    ) -> dict[str, Any]:
        """Add multiple links to an article.

        Args:
            source_id (int): Source article ID
            target_ids (List[int]): List of target article IDs
            link_type (Optional[str]): Link relationship type

        Returns:
            Dict[str, Any]: Bulk link operation result
        """
        url = f"{self.base_url}/article/{source_id}/links"
        body = {"childIDList": ",".join(str(id) for id in target_ids)}
        if link_type:
            body["linkType"] = link_type

        response = self.session.post(url, json=body)
        response.raise_for_status()
        return response.json()

    def delete_article_links(
        self,
        source_id: int,
        target_ids: list[int]
    ) -> dict[str, Any]:
        """Delete links between articles.

        Args:
            source_id (int): Source article ID
            target_ids (List[int]): Target article IDs to unlink

        Returns:
            Dict[str, Any]: Delete operation result
        """
        url = f"{self.base_url}/article/{source_id}/links"
        body = {"childIDList": ",".join(str(id) for id in target_ids)}

        response = self.session.delete(url, json=body)
        response.raise_for_status()
        return response.json()

    # ==================== Query Operations ====================

    def execute_query_by_id(
        self,
        query_id: int,
        start_at: int = 1,
        max_results: int | None = None,
        fields: str | None = None,
        search: str | None = None,
        query_param: str | None = None,
        include_text_fields: bool = True,
        additional_fields: str | None = None,
        include_query_fields: bool = True
    ) -> dict[str, Any]:
        """Execute a saved query by ID.

        Args:
            query_id (int): Query ID
            start_at (int): Starting row for pagination
            max_results (Optional[int]): Max results
            fields (Optional[str]): Specific fields to select
            search (Optional[str]): Additional search filter XML
            query_param (Optional[str]): Parameters for parameterized queries
            include_text_fields (bool): Include text fields
            additional_fields (Optional[str]): Add select fields not in query
            include_query_fields (bool): Include query-defined fields with additional_fields

        Returns:
            Dict[str, Any]: Query results

        Example:
            >>> results = client.execute_query_by_id(
            ...     query_id=123456,
            ...     max_results=50,
            ...     fields='id,title,status'
            ... )
        """
        url = f"{self.base_url}/query/execution/{query_id}"
        params = {
            "start_at": start_at,
            "include_text_fields": "Y" if include_text_fields else "N",
            "include_query_fields": "Y" if include_query_fields else "N"
        }
        if max_results:
            params["max_results"] = max_results
        if fields:
            params["fields"] = fields
        if search:
            params["search"] = search
        if query_param:
            params["query_param"] = query_param
        if additional_fields:
            params["additional_fields"] = additional_fields

        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def execute_query_by_xml(
        self,
        query_xml: str,
        start_at: int = 1,
        max_results: int | None = None,
        fields: str | None = None,
        search: str | None = None,
        query_parameters: str | None = None,
        include_text_fields: bool = True
    ) -> dict[str, Any]:
        """Execute a query using XML definition.

        Args:
            query_xml (str): Query XML definition
            start_at (int): Starting row
            max_results (Optional[int]): Max results
            fields (Optional[str]): Fields to select
            search (Optional[str]): Search filter XML
            query_parameters (Optional[str]): Query parameters
            include_text_fields (bool): Include text fields

        Returns:
            Dict[str, Any]: Query results
        """
        url = f"{self.base_url}/query/execution"
        body = {"queryXml": query_xml}
        if search:
            body["search"] = search
        if query_parameters:
            body["queryParameters"] = query_parameters

        params = {
            "start_at": start_at,
            "include_text_fields": "Y" if include_text_fields else "N"
        }
        if max_results:
            params["max_results"] = max_results
        if fields:
            params["fields"] = fields

        response = self.session.post(url, json=body, params=params)
        response.raise_for_status()
        return response.json()

    def execute_query_by_eql(
        self,
        eql: str,
        start_at: int = 1,
        max_results: int | None = None,
        include_text_fields: bool = True
    ) -> dict[str, Any]:
        """Execute a query using EQL (HSDES Query Language).

        Args:
            eql (str): EQL query string
            start_at (int): Starting row
            max_results (Optional[int]): Max results
            include_text_fields (bool): Include text fields

        Returns:
            Dict[str, Any]: Query results
        """
        url = f"{self.base_url}/query/execution/eql"
        body = {"eql": eql}

        params = {
            "start_at": start_at,
            "include_text_fields": "Y" if include_text_fields else "N"
        }
        if max_results:
            params["max_results"] = max_results

        response = self.session.post(url, json=body, params=params)
        response.raise_for_status()
        return response.json()

    def get_query_info(
        self,
        query_id: int,
        expand: str | None = None,
        fields: str | None = None
    ) -> dict[str, Any]:
        """Get information about a query.

        Args:
            query_id (int): Query ID
            expand (Optional[str]): Expand options ('metadata', 'fielddata')
            fields (Optional[str]): Specific fields to return

        Returns:
            Dict[str, Any]: Query metadata
        """
        url = f"{self.base_url}/query/{query_id}"
        params = {}
        if expand:
            params["expand"] = expand
        if fields:
            params["fields"] = fields

        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def create_query(
        self,
        query_xml: str,
        title: str | None = None,
        category: str | None = None
    ) -> dict[str, Any]:
        """Create a new saved query.

        Args:
            query_xml (str): Query XML definition
            title (Optional[str]): Query title
            category (Optional[str]): Category ('public', 'private', 'official')

        Returns:
            Dict[str, Any]: Created query info
        """
        url = f"{self.base_url}/query"
        body = {"queryXml": query_xml}
        if title:
            body["title"] = title
        if category:
            body["category"] = category

        response = self.session.post(url, json=body)
        response.raise_for_status()
        return response.json()

    def update_query(
        self,
        query_xml: str,
        query_id: int | None = None
    ) -> dict[str, Any]:
        """Update an existing query.

        Args:
            query_xml (str): Updated query XML
            query_id (Optional[int]): Query ID

        Returns:
            Dict[str, Any]: Update result
        """
        url = f"{self.base_url}/query"
        body = {"queryXml": query_xml}
        if query_id:
            body["id"] = query_id

        response = self.session.put(url, json=body)
        response.raise_for_status()
        return response.json()

    def delete_query(self, query_id: int) -> dict[str, Any]:
        """Delete a query by ID.

        Args:
            query_id (int): Query ID to delete

        Returns:
            Dict[str, Any]: Deletion result
        """
        url = f"{self.base_url}/query/{query_id}"
        response = self.session.delete(url)
        response.raise_for_status()
        return response.json()

    def copy_query(
        self,
        query_id: int,
        title: str | None = None,
        category: str | None = None
    ) -> dict[str, Any]:
        """Make a copy of an existing query.

        Args:
            query_id (int): Query ID to copy
            title (Optional[str]): Title for the copy
            category (Optional[str]): Category for the copy

        Returns:
            Dict[str, Any]: Copied query info
        """
        url = f"{self.base_url}/query/{query_id}"
        body = {}
        if title:
            body["title"] = title
        if category:
            body["category"] = category

        response = self.session.post(url, json=body)
        response.raise_for_status()
        return response.json()

    def get_query_metadata(
        self,
        query_id: int | None = None,
        owner: str | None = None,
        tag: str | None = None,
        category: str | None = None,
        fields: str = "id,title,owner,query.category,tag"
    ) -> dict[str, Any]:
        """Get query metadata.

        Args:
            query_id (Optional[int]): Filter by query ID
            owner (Optional[str]): Filter by owner IDSID
            tag (Optional[str]): Filter by tag
            category (Optional[str]): Filter by category
            fields (str): Fields to return

        Returns:
            Dict[str, Any]: Query metadata list
        """
        url = f"{self.base_url}/query/MetaData"
        params = {"fields": fields}
        if query_id:
            params["id"] = query_id
        if owner:
            params["owner"] = owner
        if tag:
            params["tag"] = tag
        if category:
            params["category"] = category

        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    # ==================== Binary/Attachment Operations ====================

    def upload_attachment(
        self,
        parent_id: int,
        file_path: str,
        description: str | None = None,
        tag: str | None = None,
        is_public: bool = True
    ) -> dict[str, Any]:
        """Upload a file as an attachment.

        Args:
            parent_id (int): Parent article ID
            file_path (str): Path to file to upload
            description (Optional[str]): Attachment description
            tag (Optional[str]): Attachment tags
            is_public (bool): Public attachment

        Returns:
            Dict[str, Any]: Upload result with attachment ID
        """
        url = f"{self.base_url}/binary/upload/{parent_id}"
        with open(file_path, 'rb') as file_content:
            files = {'file': file_content}
            data = {"is_public": str(is_public).lower()}
            if description:
                data['description'] = description
            if tag:
                data['tag'] = tag

            response = self.session.post(url, files=files, data=data)
        response.raise_for_status()
        return response.json()

    def download_attachment(
        self,
        attachment_id: int,
        output_path: str | None = None
    ) -> bytes | None:
        """Download an attachment.

        Args:
            attachment_id (int): Attachment ID
            output_path (Optional[str]): Save to file path

        Returns:
            Union[bytes, None]: File content if output_path is None
        """
        url = f"{self.base_url}/binary/{attachment_id}"
        response = self.session.get(url)
        response.raise_for_status()

        if output_path:
            with open(output_path, 'wb') as f:
                f.write(response.content)
            return None
        else:
            return response.content

    def delete_attachment(self, attachment_id: int) -> dict[str, Any]:
        """Delete an attachment.

        Args:
            attachment_id (int): Attachment ID

        Returns:
            Dict[str, Any]: Deletion result
        """
        url = f"{self.base_url}/binary/{attachment_id}"
        response = self.session.delete(url)
        response.raise_for_status()
        return response.json()

    def update_attachment(
        self,
        attachment_id: int,
        file_path: str | None = None,
        description: str | None = None,
        tag: str | None = None,
        is_public: bool | None = None
    ) -> dict[str, Any]:
        """Update attachment metadata or content.

        Args:
            attachment_id (int): Attachment ID
            file_path (Optional[str]): New file path
            description (Optional[str]): New description
            tag (Optional[str]): New tags
            is_public (Optional[bool]): Public flag

        Returns:
            Dict[str, Any]: Update result
        """
        url = f"{self.base_url}/binary/{attachment_id}"
        data = {}

        if description:
            data['description'] = description
        if tag:
            data['tag'] = tag
        if is_public is not None:
            data['is_public'] = str(is_public).lower()

        if file_path:
            with open(file_path, 'rb') as file_content:
                files = {'file': file_content}
                data['file_name'] = os.path.basename(file_path)
                response = self.session.put(url, files=files, data=data)
        else:
            response = self.session.put(url, data=data)

        response.raise_for_status()
        return response.json()

    # ==================== User Operations ====================

    def get_current_user(self, expand: str | None = None) -> dict[str, Any]:
        """Get information about the currently authenticated user.

        Args:
            expand (Optional[str]): Expand options ('personal', 'manager', 'groups')

        Returns:
            Dict[str, Any]: Current user information
        """
        url = f"{self.base_url}/user"
        params = {}
        if expand:
            params["expand"] = expand

        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def get_user_info(
        self,
        idsid: str,
        expand: str = "personal"
    ) -> dict[str, Any]:
        """Get information about a specific user.

        Args:
            idsid (str): User's IDSID
            expand (str): Info to expand ('personal', 'manager', 'groups')

        Returns:
            Dict[str, Any]: User information
        """
        url = f"{self.base_url}/user/{idsid}"
        params = {"expand": expand}

        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def get_user_by_email(self, email_id: str) -> dict[str, Any]:
        """Get user details by email ID.

        Args:
            email_id (str): User's email address

        Returns:
            Dict[str, Any]: User information
        """
        url = f"{self.base_url}/user/byemailId"
        params = {"emailId": email_id}

        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def search_users(self, user_info: dict[str, Any]) -> dict[str, Any]:
        """Search for users by various criteria.

        Args:
            user_info (Dict[str, Any]): Search parameters

        Returns:
            Dict[str, Any]: Matching users
        """
        url = f"{self.base_url}/user/info"
        response = self.session.post(url, json=user_info)
        response.raise_for_status()
        return response.json()

    def get_user_profile_image_url(
        self,
        idsid: str,
        format: str = "json"
    ) -> dict[str, Any]:
        """Get URL for user's profile picture.

        Args:
            idsid (str): User's IDSID
            format (str): Return format ('json' or 'text')

        Returns:
            Dict[str, Any]: Profile image URL
        """
        url = f"{self.base_url}/user/{idsid}/profile_img_url"
        params = {"format": format}

        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json() if format == "json" else response.text

    # ==================== Security Operations ====================

    def check_user_security(
        self,
        expand: str | None = None,
        user: str | None = None
    ) -> dict[str, Any]:
        """Check user security information.

        Args:
            expand (Optional[str]): Expansion options
            user (Optional[str]): User to check

        Returns:
            Dict[str, Any]: Security information
        """
        url = f"{self.base_url}/security/user"
        params = {}
        if expand:
            params["expand"] = expand
        if user:
            params["user"] = user

        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def get_article_security_info(
        self,
        article_id: int,
        expand: str | None = None
    ) -> dict[str, Any]:
        """Get security information for an article.

        Args:
            article_id (int): Article ID
            expand (Optional[str]): Expansion options

        Returns:
            Dict[str, Any]: Article security information
        """
        url = f"{self.base_url}/security/article/{article_id}"
        params = {}
        if expand:
            params["expand"] = expand

        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    # ==================== Utility Methods ====================

    def get_api_info(self) -> dict[str, Any]:
        """Get general API information.

        Returns:
            Dict[str, Any]: API information
        """
        url = f"{self.base_url}/"
        response = self.session.get(url)
        response.raise_for_status()
        return response.json()

    def get_server_node_info(self) -> dict[str, Any]:
        """Get server node information.

        Returns:
            Dict[str, Any]: Server node details
        """
        url = f"{self.base_url}/info/node"
        response = self.session.get(url)
        response.raise_for_status()
        return response.json()

    def search_directory(
        self,
        search: str,
        exact: bool = False,
        search_type: str = "user"
    ) -> dict[str, Any]:
        """Search Active Directory.

        Args:
            search (str): Search term
            exact (bool): Exact match
            search_type (str): Type to search ('user', 'group')

        Returns:
            Dict[str, Any]: Directory search results
        """
        url = f"{self.base_url}/directory"
        params = {
            "search": search,
            "exact": str(exact).lower(),
            "type": search_type
        }

        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def validate_component(self, component_ids: str) -> dict[str, Any]:
        """Validate comma-separated component IDs.

        Args:
            component_ids (str): Comma-separated component IDs

        Returns:
            Dict[str, Any]: Validation results
        """
        url = f"{self.base_url}/component/validation/{component_ids}"
        response = self.session.get(url)
        response.raise_for_status()
        return response.json()

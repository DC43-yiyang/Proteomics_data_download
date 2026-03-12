import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class NCBIClient:
    """Low-level wrapper around NCBI E-utilities with built-in rate limiting.

    Rate limits:
        - Without API key: 3 requests/second (0.34s interval)
        - With API key:   10 requests/second (0.1s interval)
    """

    BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    def __init__(
        self,
        api_key: Optional[str] = None,
        email: str = "",
        tool: str = "geo_agent",
    ):
        self.api_key = api_key
        self.email = email
        self.tool = tool
        self._min_interval = 0.1 if api_key else 0.34
        # GEO acc.cgi is a web endpoint, not E-utilities — doesn't accept API keys
        # Use a conservative rate to avoid being blocked
        self._min_interval_geo = 0.25  # 4 req/s for GEO web endpoint
        self._last_request_time = 0.0
        self.session = requests.Session()

    def _rate_limit(self, interval: float | None = None):
        """Block until enough time has passed since the last request."""
        min_interval = interval or self._min_interval
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_time = time.monotonic()

    def _base_params(self) -> dict:
        params = {"tool": self.tool, "email": self.email}
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    def _request_with_retry(
        self, url: str, params: dict, max_retries: int = 3
    ) -> requests.Response:
        """Make a request with exponential backoff retry on 429/5xx."""
        for attempt in range(max_retries):
            self._rate_limit()
            resp = self.session.get(url, params=params, timeout=30)

            if resp.status_code == 429 or resp.status_code >= 500:
                wait = 2**attempt
                logger.warning(
                    f"HTTP {resp.status_code} from NCBI. "
                    f"Retrying in {wait}s (attempt {attempt + 1}/{max_retries})..."
                )
                time.sleep(wait)
                continue

            resp.raise_for_status()
            return resp

        raise RuntimeError(
            f"NCBI request failed after {max_retries} retries: {url}"
        )

    def esearch(self, db: str, term: str, retmax: int = 100) -> dict:
        """Search a database and return matching UIDs.

        Args:
            db: Database name (e.g. "gds" for GEO DataSets)
            term: Search query string
            retmax: Maximum number of UIDs to return

        Returns:
            Parsed JSON response containing UIDs in result["esearchresult"]["idlist"]
        """
        params = {
            **self._base_params(),
            "db": db,
            "term": term,
            "retmax": retmax,
            "retmode": "json",
        }
        resp = self._request_with_retry(f"{self.BASE_URL}/esearch.fcgi", params)
        return resp.json()

    def esummary(self, db: str, ids: list[str]) -> dict:
        """Fetch document summaries for a list of UIDs.

        Batches automatically if more than 200 IDs are provided.

        Args:
            db: Database name
            ids: List of NCBI UIDs

        Returns:
            Merged JSON response with all summaries
        """
        batch_size = 200
        all_results = {}

        for i in range(0, len(ids), batch_size):
            batch = ids[i : i + batch_size]
            params = {
                **self._base_params(),
                "db": db,
                "id": ",".join(batch),
                "retmode": "json",
            }
            resp = self._request_with_retry(
                f"{self.BASE_URL}/esummary.fcgi", params
            )
            data = resp.json()

            if "result" in data:
                for key, val in data["result"].items():
                    if key != "uids":
                        all_results[key] = val

            batch_num = i // batch_size + 1
            total_batches = (len(ids) + batch_size - 1) // batch_size
            if total_batches > 1:
                logger.info(
                    f"Fetched summary batch {batch_num}/{total_batches}"
                )

        return {"result": all_results}

    def efetch(
        self,
        db: str,
        ids: list[str],
        rettype: str = "full",
        retmode: str = "xml",
    ) -> str:
        """Fetch full records (usually XML).

        Args:
            db: Database name
            ids: List of NCBI UIDs
            rettype: Return type
            retmode: Return mode ("xml" or "text")

        Returns:
            Raw response text
        """
        params = {
            **self._base_params(),
            "db": db,
            "id": ",".join(ids),
            "rettype": rettype,
            "retmode": retmode,
        }
        resp = self._request_with_retry(f"{self.BASE_URL}/efetch.fcgi", params)
        return resp.text

    def fetch_family_soft(self, accession: str) -> str:
        """Fetch GEO Family SOFT format (targ=all) for a single GSE accession.

        Returns ^SERIES block (with series-level supplementary files) and
        all ^SAMPLE blocks with per-sample metadata (title, characteristics,
        molecule, library_source, supplementary files).
        Responses are large, so uses a 60s timeout.

        Args:
            accession: GSE accession number (e.g. "GSE317605")

        Returns:
            Raw Family SOFT format text containing series and sample blocks
        """
        url = "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi"
        params = {"acc": accession, "targ": "all", "form": "text", "view": "brief"}
        self._rate_limit(interval=self._min_interval_geo)
        resp = self.session.get(url, params=params, timeout=60)
        resp.raise_for_status()
        return resp.text

    def fetch_family_soft_batch(self, accessions: list[str]) -> dict[str, str]:
        """Fetch Family SOFT format for multiple accessions.

        Args:
            accessions: List of GSE accession numbers

        Returns:
            Dict mapping accession -> raw Family SOFT text (empty string on error)
        """
        results = {}
        total = len(accessions)
        for i, acc in enumerate(accessions, 1):
            try:
                results[acc] = self.fetch_family_soft(acc)
            except Exception as e:
                logger.warning(f"Failed to fetch Family SOFT for {acc}: {e}")
                results[acc] = ""

            if total > 10 and i % 20 == 0:
                logger.info(f"Fetched Family SOFT metadata {i}/{total}")

        return results

    def fetch_geo_soft(self, accession: str) -> str:
        """Fetch GEO Series SOFT format for a single accession.

        This uses GEO's own acc.cgi endpoint (not E-utilities) which returns
        fields not available via esummary, including Overall design,
        contributors, and complete supplementary file listings.

        Args:
            accession: GSE accession number (e.g. "GSE268991")

        Returns:
            Raw SOFT format text
        """
        url = "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi"
        params = {"acc": accession, "targ": "self", "form": "text", "view": "brief"}
        self._rate_limit(interval=self._min_interval_geo)
        resp = self.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.text

    def fetch_geo_soft_batch(self, accessions: list[str]) -> dict[str, str]:
        """Fetch SOFT format for multiple accessions.

        Args:
            accessions: List of GSE accession numbers

        Returns:
            Dict mapping accession -> raw SOFT text
        """
        results = {}
        total = len(accessions)
        for i, acc in enumerate(accessions, 1):
            try:
                results[acc] = self.fetch_geo_soft(acc)
            except Exception as e:
                logger.warning(f"Failed to fetch SOFT for {acc}: {e}")
                results[acc] = ""

            if total > 10 and i % 20 == 0:
                logger.info(f"Fetched SOFT metadata {i}/{total}")

        return results

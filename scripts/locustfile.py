import os

from locust import HttpUser, between, task


class QueryUser(HttpUser):
    wait_time = between(0, 0)

    def on_start(self) -> None:
        self.agent_id = os.environ["TRUERAG_AGENT_ID"]
        self.headers = {"X-API-Key": os.environ["TRUERAG_API_KEY"]}

    @task
    def query_agent(self) -> None:
        self.client.post(
            f"/v1/{self.agent_id}/query",
            json={"query": "What are the key capabilities of this document?", "top_k": 5},
            headers=self.headers,
        )

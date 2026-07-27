from abc import ABC, abstractmethod


class LlmClient(ABC):
    @abstractmethod
    def chat(self, prompt: str) -> str:
        raise NotImplementedError


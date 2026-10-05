import asyncio

from viam.module.module import Module

from .models.relay import Lcus2Relay  # noqa: F401

if __name__ == "__main__":
    asyncio.run(Module.run_from_registry())

"""Fixed local inference and surrogate randomness."""

import random

RANDOM_SEED = 42

def seed_local():
    import numpy as np
    import torch
    from faker import Faker

    random.seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)
    torch.manual_seed(RANDOM_SEED)
    Faker.seed(RANDOM_SEED)
    torch.use_deterministic_algorithms(True)
    torch.set_num_threads(1)


SEED_CONFIGURATION = {
    "seed": RANDOM_SEED,
    "generators": ["python.random", "numpy.random", "torch", "Faker"],
    "torch_deterministic_algorithms": True,
    "torch_num_threads": 1,
    "surrogate_seed": "BLAKE2b(seed, source A0 run/case/line, entity type, canonical surface)",
    "scope": "same inputs, model files, dependency versions and CPU environment",
}

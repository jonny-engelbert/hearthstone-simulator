"""Pinned SplitMix64 + rejection sampling; all RNG state lives in the match."""
MASK = (1 << 64) - 1


def new(seed):
    if type(seed) is not int:
        raise ValueError('seed must be an integer')
    return dict(algorithm='splitmix64-v1', state=seed & MASK, draws=0)


def next_u64(rng):
    rng['state'] = (rng['state'] + 0x9E3779B97F4A7C15) & MASK
    value = rng['state']
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & MASK
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & MASK
    rng['draws'] += 1
    return value ^ (value >> 31)


def randbelow(rng, bound):
    if type(bound) is not int or not 0 < bound <= 1 << 64:
        raise ValueError('invalid RNG bound')
    limit = (1 << 64) - ((1 << 64) % bound)
    while True:
        value = next_u64(rng)
        if value < limit:
            return value % bound


def shuffle(rng, values):
    for index in range(len(values) - 1, 0, -1):
        other = randbelow(rng, index + 1)
        values[index], values[other] = values[other], values[index]

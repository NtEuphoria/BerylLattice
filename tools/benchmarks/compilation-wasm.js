/* Research-only shared Wasm local-declaration reader (Node and browser Worker). */
function localCount(bytes) {
  if ([0,97,115,109,1,0,0,0].some((value, index) => bytes[index] !== value)) throw new Error('invalid Wasm header');
  let position = 8, total = 0;
  const leb = end => {
    let value = 0, shift = 0;
    while (position < end && shift < 35) {
      const byte = bytes[position++];
      value += (byte & 127) * 2 ** shift;
      if (byte < 128) return value;
      shift += 7;
    }
    throw new Error('truncated Wasm integer');
  };
  while (position < bytes.length) {
    const section = bytes[position++], length = leb(bytes.length), end = position + length;
    if (end > bytes.length) throw new Error('truncated Wasm section');
    if (section === 10) {
      const count = leb(end);
      for (let index = 0; index < count; index++) {
        const length = leb(end), bodyEnd = position + length;
        if (bodyEnd > end) throw new Error('truncated Wasm body');
        const groups = leb(bodyEnd);
        for (let group = 0; group < groups; group++) {
          total += leb(bodyEnd);
          if (position >= bodyEnd) throw new Error('truncated local type');
          position++;
        }
        position = bodyEnd;
      }
    }
    position = end;
  }
  return total;
}

if (typeof module !== 'undefined') module.exports = {localCount};

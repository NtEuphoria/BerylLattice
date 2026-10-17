module axiom_buffer_fixture

fn ax_preflight(let input: List<i32>) -> i32 {
    for i in 0..6 {
        let value: i32 = input.get(i)
        if value < 0 || value > 1023 { return i }
    }
    return -1
}

fn ax_body(let input: List<i32>, inout output: List<i32>,
           inout scratch: List<i32>) {
    for i in 0..6 {
        let value: i32 = input.get(i)
        let left: i32 = value + 1
        let right: i32 = value + 1
        let producer: i32 = left * right
        scratch.set(i, producer)
    }
    for c in 0..2 {
        let p00: i32 = scratch.get(c)
        let p01: i32 = scratch.get(c + 1)
        let p10: i32 = scratch.get(c + 3)
        let p11: i32 = scratch.get(c + 4)
        let sum2: i32 = p00 + p01
        let sum3: i32 = sum2 + p10
        let sum4: i32 = sum3 + p11
        output.set(c, sum4)
    }
}

module axiom_generated

fn ax_kernel(input: [i32; 4], inout output: [i32; 1]) -> i32 {
    if input[0] < 0 || input[0] > 1023 { return 0 }
    if input[1] < 0 || input[1] > 1023 { return 1 }
    if input[2] < 0 || input[2] > 1023 { return 2 }
    if input[3] < 0 || input[3] > 1023 { return 3 }
    let ax_v0: i32 = 1
    let ax_v1: i32 = input[0]
    let ax_v2: i32 = ax_v1 + ax_v0
    let ax_v3: i32 = ax_v2 * ax_v2
    let ax_v4: i32 = input[1]
    let ax_v5: i32 = ax_v4 + ax_v0
    let ax_v6: i32 = ax_v5 * ax_v5
    let ax_v7: i32 = input[2]
    let ax_v8: i32 = ax_v7 + ax_v0
    let ax_v9: i32 = ax_v8 * ax_v8
    let ax_v10: i32 = input[3]
    let ax_v11: i32 = ax_v10 + ax_v0
    let ax_v12: i32 = ax_v11 * ax_v11
    let ax_v13: i32 = ax_v3 + ax_v6
    let ax_v14: i32 = ax_v13 + ax_v9
    let ax_v15: i32 = ax_v14 + ax_v12
    output[0] = ax_v15
    return -1
}

test "axiom witness" {
    let input: [i32; 4] = [0, 1, 2, 3]
    var output: [i32; 1] = [-99]
    let status: i32 = ax_kernel(input, inout output)
    println(status)
    println(input[0])
    println(input[1])
    println(input[2])
    println(input[3])
    println(output[0])
}

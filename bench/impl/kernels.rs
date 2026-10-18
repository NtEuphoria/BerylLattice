// Rust baseline. Build: rustc -C opt-level=3 kernels.rs -o kernels
// argv: kernel pattern a b min_ms max_reps -> one JSON line on stdout.
use std::hint::black_box;
use std::time::Instant;

fn value(p: &str, i: usize) -> i32 {
    match p {
        "hash" => ((i as u32).wrapping_mul(2654435761) >> 22) as i32,
        "ramp" => (i % 1024) as i32,
        "alt" => 1023 * (i & 1) as i32,
        "zeros" => 0,
        "max" => 1023,
        _ => panic!("unknown pattern"),
    }
}

fn window(h: usize, w: usize, x: &[i32], o: &mut [i64], f: impl Fn(&[i32], &[i32], &[i32], usize) -> i64) {
    let cols = w + 2;
    for r in 0..h {
        let (a, b, c) = (&x[r * cols..], &x[(r + 1) * cols..], &x[(r + 2) * cols..]);
        for j in 0..w { o[r * w + j] = f(a, b, c, j); }
    }
}

fn run(k: &str, h: usize, w: usize, x: &[i32], o: &mut [i64]) {
    match k {
        "sq2x2" => {
            let cols = w + 1;
            let p = |v: i32| { let v = v as i64 + 1; v * v };
            for r in 0..h { for c in 0..w {
                let i = r * cols + c;
                o[r * w + c] = p(x[i]) + p(x[i + 1]) + p(x[i + cols]) + p(x[i + cols + 1]);
            }}
        }
        "stencil1d3" => for i in 0..h { o[i] = x[i] as i64 + 2 * x[i + 1] as i64 + x[i + 2] as i64; },
        "box3x3" => window(h, w, x, o, |a, b, c, j| (a[j] + a[j+1] + a[j+2] + b[j] + b[j+1] + b[j+2]
            + c[j] + c[j+1] + c[j+2]) as i64),
        "laplace5" => window(h, w, x, o, |a, b, c, j| 4 * b[j+1] as i64 - a[j+1] as i64 - c[j+1] as i64
            - b[j] as i64 - b[j+2] as i64),
        "conv3x3" => window(h, w, x, o, |a, b, c, j| (a[j] + 2*a[j+1] + a[j+2] + 2*b[j] + 4*b[j+1]
            + 2*b[j+2] + c[j] + 2*c[j+1] + c[j+2]) as i64),
        "life" => window(h, w, x, o, |a, b, c, j| {
            let n = (a[j]&1) + (a[j+1]&1) + (a[j+2]&1) + (b[j]&1) + (b[j+2]&1) + (c[j]&1) + (c[j+1]&1) + (c[j+2]&1);
            (n == 3 || (n == 2 && b[j+1] & 1 == 1)) as i64
        }),
        "polymap" => for i in 0..h { let v = x[i] as i64; o[i] = v * v * v + 3 * v + 7; },
        "transpose" => for r in 0..h { for c in 0..w { o[c * h + r] = x[r * w + c] as i64; } },
        "maxpool2" => {
            let cols = 2 * w;
            for r in 0..h { for c in 0..w {
                let (t, u) = (2 * r * cols + 2 * c, (2 * r + 1) * cols + 2 * c);
                o[r * w + c] = x[t].max(x[t + 1]).max(x[u]).max(x[u + 1]) as i64;
            }}
        }
        "sum" => o[0] = x.iter().map(|&v| v as i64).sum(),
        "dot" => o[0] = x[..h].iter().zip(&x[h..]).map(|(&p, &q)| p as i64 * q as i64).sum(),
        "scan" => { let mut s = 0i64; for i in 0..h { s += x[i] as i64; o[i] = s; } }
        "hist" => { o.fill(0); for &v in x { o[(v >> 4) as usize] += 1; } }
        "matmul" => {
            let n = h; let (p, q) = x.split_at(n * n);
            o.fill(0);
            for i in 0..n { for k in 0..n {
                let pv = p[i * n + k] as i64; let row = &mut o[i * n..(i + 1) * n]; let qr = &q[k * n..(k + 1) * n];
                for j in 0..n { row[j] += pv * qr[j] as i64; }
            }}
        }
        _ => unreachable!(),
    }
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    assert!(args.len() == 7, "usage: kernel pattern a b min_ms max_reps");
    let (k, pat) = (args[1].as_str(), args[2].as_str());
    let n: Vec<usize> = args[3..7].iter().map(|s| s.parse().unwrap()).collect();
    let (a, b, min_ns, max_reps) = (n[0], n[1], n[2] as u128 * 1_000_000, n[3].max(3));
    let io = match k {
        "sq2x2" => ((a+1)*(b+1), a*b), "stencil1d3" => (a+2, a),
        "box3x3" | "laplace5" | "conv3x3" | "life" => ((a+2)*(b+2), a*b),
        "polymap" | "scan" => (a, a), "transpose" => (a*b, a*b), "maxpool2" => (4*a*b, a*b),
        "sum" => (a, 1), "dot" => (2*a, 1), "hist" => (a, 64), "matmul" => (2*a*a, a*a),
        _ => { println!("{{\"impl\":\"rust\",\"kernel\":\"{}\",\"status\":\"unsupported\"}}", k); return; }
    };
    let x: Vec<i32> = (0..io.0).map(|i| value(pat, i)).collect();
    let mut o = vec![0i64; io.1];
    run(k, a, b, &x, &mut o); // untimed warm-up
    // Calibrate calls per sample so one sample spans >= 1 ms.
    let mut inner: u128 = 1;
    loop {
        let t = Instant::now();
        for _ in 0..inner { run(k, a, b, black_box(&x), &mut o); black_box(&o); }
        if t.elapsed().as_nanos() >= 1_000_000 || inner >= 1 << 22 { break; }
        inner *= 2;
    }
    let mut s: Vec<u128> = Vec::new();
    let mut total: u128 = 0;
    while s.len() < 3 || (total < min_ns && s.len() < max_reps) {
        let t = Instant::now();
        for _ in 0..inner { run(k, a, b, black_box(&x), &mut o); black_box(&o); }
        let batch = t.elapsed().as_nanos();
        s.push(batch / inner);
        total += batch;
    }
    const M: i64 = 1_000_000_007;
    let mut acc = 0i64;
    for (i, &v) in o.iter().enumerate() { acc = (acc + ((v % M) + M) % M * (i as i64 % 65521 + 1)) % M; }
    s.sort();
    let med = if s.len() % 2 == 1 { s[s.len() / 2] } else { (s[s.len() / 2 - 1] + s[s.len() / 2]) / 2 };
    println!("{{\"impl\":\"rust\",\"kernel\":\"{}\",\"status\":\"ok\",\"n_out\":{},\"checksum\":{},\"reps\":{},\"inner\":{},\"ns_min\":{},\"ns_median\":{},\"ns_total\":{}}}",
             k, io.1, acc, s.len(), inner, s[0], med, total);
}
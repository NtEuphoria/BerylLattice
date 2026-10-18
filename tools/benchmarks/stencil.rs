// Bounded direct stencil baseline. Compile with rustc -O.
use std::io::{self, Read};
fn main() {
    let mut text = String::new();
    io::stdin().read_to_string(&mut text).unwrap();
    let values: Vec<i32> = text.split_whitespace().map(|x| x.parse().unwrap()).collect();
    assert!(values.len() >= 2);
    let (h, w) = (values[0], values[1]);
    assert!(h > 0 && h <= 255 && w > 0 && w <= 255 && (h+1)*(w+1) <= 256);
    let (h, w) = (h as usize, w as usize);
    let a = &values[2..];
    assert_eq!(a.len(), (h+1)*(w+1));
    assert!(a.iter().all(|&x| (0..=1023).contains(&x)));
    let mut out = Vec::with_capacity(h*w);
    for r in 0..h { for c in 0..w {
        let i = r*(w+1)+c;
        let (x,y,z,t) = (a[i]+1,a[i+1]+1,a[i+w+1]+1,a[i+w+2]+1);
        out.push(((x*x+y*y)+z*z)+t*t);
    }}
    println!("{:?}", out);
}

let counter () = let r = ref 0 in for i = 0 to 9 do r := !r + i done; !r

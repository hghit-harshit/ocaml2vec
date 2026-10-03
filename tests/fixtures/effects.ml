type _ Effect.t += Ask : int Effect.t

let ask () = Effect.perform Ask

(* %runstack / %resume / %reperform are not exported by Stdlib.Effect;
   declare them directly so the fixture exercises those primitives. *)
external runstack : Obj.t -> (Obj.t -> Obj.t) -> Obj.t -> Obj.t = "%runstack"
external resume : Obj.t -> (Obj.t -> Obj.t) -> Obj.t -> Obj.t -> Obj.t
  = "%resume"
external reperform : Obj.t -> Obj.t -> Obj.t -> Obj.t = "%reperform"

let run_raw stack f x = runstack stack f x
let resume_raw stack f x last = resume stack f x last
let reperform_raw eff k last = reperform eff k last

let handled () =
  Effect.Deep.match_with (fun () -> ask () + ask ()) ()
    { retc = (fun x -> x);
      exnc = raise;
      effc = (fun (type a) (e : a Effect.t) ->
        match e with
        | Ask -> Some (fun (k : (a, _) Effect.Deep.continuation) ->
            Effect.Deep.continue k 21)
        | _ -> None) }

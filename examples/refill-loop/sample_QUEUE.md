# QUEUE - one line = one unit of work. Take from the top.

**The last row must never carry a date.** The last row is the one that generates new
rows; once it is scheduled, the queue can only get shorter.

Marker: `(kind date)` - kind is `routine` (a script can do it), `judgment` (someone has
to decide something) or `upstream` (the plan itself is in question). The date means
"not before this day"; `MM-DD` and `YYYY-MM-DD` both work. `(wait)` means the row is
blocked on a human and the loop skips it.

- [x] (routine) shelf A | daily numbers | done 2026-09-14
- [ ] (routine 09-16) shelf A | D+3 numbers for the three things put up on 09-13
- [ ] (judgment) (wait) shelf B | needs the owner's yes/no on the account
- [ ] (judgment) shelf C | put one thing up and record the first reaction
- [ ] (judgment) generative order | write next week's order, the one that produces new rows

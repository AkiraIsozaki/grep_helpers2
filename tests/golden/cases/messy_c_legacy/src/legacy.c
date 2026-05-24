/* legacy 777 handler - see ticket #777 */
int	proc(int x){
	if (x == 777) {        /* 777 check */
		int a=1; int b=777; int c=3;
		return b;
	}
	// dead: int old = 777;
	return 0;   
}

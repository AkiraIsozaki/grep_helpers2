v_code VARCHAR2(10);
v_code := 'X';
SELECT DECODE(st,1,'OK','NG') FROM dual;

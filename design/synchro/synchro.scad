$fn=50;

difference(){
cube([13,40,50]);
translate([-7.01,20,30])rotate([0,90,0])synchro();

    translate([6.5,12,0])cylinder(d=4.8,h=55);
    translate([6.5,20,0])cylinder(d=4.8,h=55);
    translate([6.5,28,0])cylinder(d=4.8,h=55);
    
        translate([6.5,12,6])cylinder(d=6.5,h=30);
    translate([6.5,20,6])cylinder(d=6.5,h=30);
    translate([6.5,28,6])cylinder(d=6.5,h=30);
}

module synchro(){
   cylinder(d=37,h=17);
cylinder(d=16,h=22); 

for(i=[0:90:360]){
   translate([10.25*sin(i),10.25*cos(i),17])cylinder(d=3.2,h=10);
}    
    
}

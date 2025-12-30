$fn=20;

plate(5,5);


module plate(l,w){
    difference(){
        hull(){
            for(j=[0:1:w-1]){
            for(i=[0:1:l-1]){
            translate([i*7.97,j*7.97,0])cylinder(d=7.38,h=7.76);
            }
        }
        }
        for(j=[0:1:w-1]){
        for(i=[0:1:l]){
        translate([i*7.97,j*7.97,0])peghole();
        }
    }
    }
}



module beam(l){
    difference(){
        hull(){
            for(i=[0:1:l-1]){
            translate([i*7.97,0,0])cylinder(d=7.38,h=7.76);
            }
        }
        for(i=[0:1:l]){
        translate([i*7.97,0,0])peghole();
        }
    }
}

module peghole(){
    translate([0,0,-0.01])cylinder(d=4.8,h=7.76+0.02);
    translate([0,0,-0.01])cylinder(d=6.2,h=0.8+0.01);
    translate([0,0,7.76-0.8+0.01])cylinder(d=6.2,h=0.8+0.01);
}